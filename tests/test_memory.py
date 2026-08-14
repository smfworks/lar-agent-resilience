"""Tests for agent_resilience.memory — MemoryManager, InMemoryProvider, FileMemoryProvider.

Covers: store/retrieve/search for both providers, MemoryManager tiered recall,
deduplication, max_items eviction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_resilience.memory import (
    FileMemoryProvider,
    InMemoryProvider,
    MemoryManager,
)


@pytest.fixture
def in_memory():
    return InMemoryProvider(max_items=5)


@pytest.fixture
def file_memory(tmp_path: Path):
    return FileMemoryProvider(tmp_path / "memory_store")


@pytest.fixture
def manager(in_memory, file_memory):
    return MemoryManager(short_term=in_memory, long_term=file_memory)


class TestInMemoryProvider:
    async def test_store_and_retrieve(self, in_memory):
        await in_memory.store("key1", "value1")
        result = await in_memory.retrieve("key1")
        assert result == "value1"

    async def test_retrieve_nonexistent(self, in_memory):
        result = await in_memory.retrieve("nonexistent")
        assert result is None

    async def test_store_with_metadata(self, in_memory):
        await in_memory.store("key1", "value1", metadata={"source": "test"})
        results = await in_memory.search("value1")
        assert len(results) == 1
        assert results[0]["metadata"] == {"source": "test"}

    async def test_search_finds_matches(self, in_memory):
        await in_memory.store("key1", "hello world")
        await in_memory.store("key2", "goodbye world")
        results = await in_memory.search("hello")
        assert len(results) == 1
        assert results[0]["key"] == "key1"

    async def test_search_limit(self, in_memory):
        for i in range(10):
            await in_memory.store(f"key{i}", f"common word item{i}")
        results = await in_memory.search("common", limit=3)
        assert len(results) == 3

    async def test_search_no_results(self, in_memory):
        await in_memory.store("key1", "hello")
        results = await in_memory.search("nonexistent_query")
        assert results == []

    async def test_max_items_eviction(self, in_memory):
        # max_items=5, so 6th item should evict the oldest
        for i in range(6):
            await in_memory.store(f"key{i}", f"value{i}")
        # key0 should have been evicted
        result = await in_memory.retrieve("key0")
        assert result is None
        # key5 should exist
        result = await in_memory.retrieve("key5")
        assert result == "value5"

    async def test_store_overwrites(self, in_memory):
        await in_memory.store("key1", "original")
        await in_memory.store("key1", "updated")
        result = await in_memory.retrieve("key1")
        assert result == "updated"


class TestFileMemoryProvider:
    async def test_store_and_retrieve(self, file_memory):
        await file_memory.store("key1", "value1")
        result = await file_memory.retrieve("key1")
        assert result == "value1"

    async def test_retrieve_nonexistent(self, file_memory):
        result = await file_memory.retrieve("nonexistent")
        assert result is None

    async def test_store_with_metadata(self, file_memory):
        await file_memory.store("key1", "value1", metadata={"tag": "important"})
        results = await file_memory.search("value1")
        assert len(results) == 1
        assert results[0]["metadata"] == {"tag": "important"}

    async def test_search_finds_matches(self, file_memory):
        await file_memory.store("key1", "hello world")
        await file_memory.store("key2", "goodbye world")
        results = await file_memory.search("hello")
        assert len(results) == 1
        assert results[0]["key"] == "key1"

    async def test_search_limit(self, file_memory):
        for i in range(10):
            await file_memory.store(f"key{i}", f"common word item{i}")
        results = await file_memory.search("common", limit=3)
        assert len(results) <= 3

    async def test_creates_directory(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "memory"
        FileMemoryProvider(nested)
        assert nested.exists()

    async def test_persistence_across_instances(self, tmp_path: Path):
        base = tmp_path / "persist_memory"
        provider1 = FileMemoryProvider(base)
        await provider1.store("persist-key", "persist-value")

        provider2 = FileMemoryProvider(base)
        result = await provider2.retrieve("persist-key")
        assert result == "persist-value"

    async def test_caching(self, file_memory):
        await file_memory.store("cached-key", "cached-value")
        # First retrieve loads from disk and caches
        await file_memory.retrieve("cached-key")
        # Second retrieve should come from cache
        result = await file_memory.retrieve("cached-key")
        assert result == "cached-value"


class TestMemoryManager:
    async def test_store_context_short_term(self, manager):
        await manager.store_context("key1", "value1")
        # Should be in short-term
        result = await manager.recall("key1")
        assert result == "value1"

    async def test_store_context_persist(self, manager, in_memory, file_memory):
        await manager.store_context("key1", "value1", persist=True)
        # Should be in both short-term and long-term
        short_result = await in_memory.retrieve("key1")
        long_result = await file_memory.retrieve("key1")
        assert short_result == "value1"
        assert long_result == "value1"

    async def test_recall_falls_through_to_long_term(self, manager, in_memory, file_memory):
        # Store only in long-term
        await file_memory.store("lt-key", "lt-value")
        # Recall should find it in long-term and promote to short-term
        result = await manager.recall("lt-key")
        assert result == "lt-value"
        # Should now be in short-term too
        short_result = await in_memory.retrieve("lt-key")
        assert short_result == "lt-value"

    async def test_recall_nonexistent(self, manager):
        result = await manager.recall("nonexistent")
        assert result is None

    async def test_search_combines_both_tiers(self, manager, in_memory, file_memory):
        await in_memory.store("st-key", "common keyword st")
        await file_memory.store("lt-key", "common keyword lt")
        results = await manager.search("common", limit=10)
        assert len(results) == 2

    async def test_search_deduplicates(self, manager, in_memory, file_memory):
        # Store same key in both tiers
        await in_memory.store("dup-key", "shared value")
        await file_memory.store("dup-key", "shared value")
        results = await manager.search("shared", limit=10)
        assert len(results) == 1  # deduplicated by key

    async def test_search_respects_limit(self, manager, in_memory):
        for i in range(10):
            await in_memory.store(f"key{i}", f"common item{i}")
        results = await manager.search("common", limit=3)
        assert len(results) <= 3
