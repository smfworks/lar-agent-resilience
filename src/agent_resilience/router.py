"""Model fallback router — public name promised by README."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoutedModel:
    model_id: str


class ModelRouter:
    """Primary + fallback chain. advance() moves to the next model."""

    def __init__(self, primary: str, fallbacks: list[str] | None = None):
        chain = [primary, *(fallbacks or [])]
        self.models = [RoutedModel(m) for m in chain if m]
        self._index = 0
        self.history: list[str] = []

    @property
    def current(self) -> RoutedModel:
        return self.models[self._index]

    def has_fallback(self) -> bool:
        return self._index + 1 < len(self.models)

    def advance(self, reason: str = "") -> RoutedModel | None:
        if not self.has_fallback():
            return None
        self.history.append(reason)
        self._index += 1
        return self.current
