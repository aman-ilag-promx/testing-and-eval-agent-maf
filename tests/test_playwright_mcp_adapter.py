"""Tests for the observation-only Playwright MCP adapter."""

from __future__ import annotations

from typing import Any

import pytest

from src.config import Settings
from src.models.enums import EvidenceType, FailureSource
from src.tools.playwright_mcp_adapter import (
    PlaywrightMCPAdapter,
    PlaywrightMCPTransportError,
    StdioPlaywrightMCPTransport,
)


class FakePlaywrightMCPTransport:
    """In-memory transport used to verify adapter behavior without a browser."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self) -> set[str]:
        return {"browser_navigate", "browser_snapshot", "browser_take_screenshot"}

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": name}]}

    def close(self) -> None:
        return None


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(PLAYWRIGHT_MCP_ENABLED=enabled)


def test_disabled_adapter_never_calls_transport() -> None:
    transport = FakePlaywrightMCPTransport()

    result = PlaywrightMCPAdapter(_settings(enabled=False), transport).take_snapshot(
        "https://example.test"
    )

    assert not result.success
    assert result.errors[0].code == "MCP_DISABLED"
    assert transport.calls == []


def test_snapshot_navigates_then_collects_observation() -> None:
    transport = FakePlaywrightMCPTransport()

    result = PlaywrightMCPAdapter(_settings(), transport).take_snapshot("https://example.test")

    assert result.success
    assert transport.calls == [
        ("browser_navigate", {"url": "https://example.test"}),
        ("browser_snapshot", {}),
    ]
    observation = result.metadata["observations"][0]
    assert observation.evidence_type is EvidenceType.MCP_OBSERVATION
    assert result.metadata["execution_performed"] is False


def test_invalid_target_makes_no_mcp_calls() -> None:
    transport = FakePlaywrightMCPTransport()

    result = PlaywrightMCPAdapter(_settings(), transport).take_screenshot("file:///private/data")

    assert not result.success
    assert result.errors[0].code == "MCP_INVALID_TARGET"
    assert result.errors[0].failure_source is FailureSource.CONFIGURATION
    assert transport.calls == []


def test_locator_discovery_records_requested_behavior() -> None:
    transport = FakePlaywrightMCPTransport()

    result = PlaywrightMCPAdapter(_settings(), transport).discover_locators(
        "https://example.test",
        "find the sign-in form",
    )

    assert result.success
    observation = result.metadata["observations"][0]
    assert observation.metadata["requested_description"] == "find the sign-in form"


def test_stdio_transport_rejects_browser_write_tools_before_starting() -> None:
    transport = StdioPlaywrightMCPTransport(_settings())

    with pytest.raises(PlaywrightMCPTransportError, match="not permitted"):
        transport.call_tool("browser_click", {"ref": "button"})