"""Packaging and public-API import contract."""

from importlib import metadata


def test_public_exports():
    import agent_resilience
    from agent_resilience import Agent, Checkpoint, ModelRouter

    assert Agent is agent_resilience.Agent
    assert ModelRouter is agent_resilience.ModelRouter
    assert Checkpoint is agent_resilience.Checkpoint
    assert "Agent" in agent_resilience.__all__
    assert "ModelRouter" in agent_resilience.__all__
    assert "Checkpoint" in agent_resilience.__all__


def test_tools_is_a_package():
    import agent_resilience.tools.builtin as builtin
    from agent_resilience.tools import Tool, ToolRegistry, ToolResult

    assert Tool is not None
    assert ToolRegistry is not None
    assert ToolResult is not None
    assert hasattr(builtin, "ExecTool")
    assert hasattr(builtin, "WebFetchTool")


def test_package_metadata_name():
    dist = metadata.distribution("agent-resilience")
    assert dist.version
    names = {ep.name for ep in metadata.entry_points().select(group="console_scripts")}
    assert "lar" in names
