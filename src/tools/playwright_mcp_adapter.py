"""Observation-only Playwright MCP adapter for browser-reachable targets."""

from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlparse

from src.config import PROJECT_ROOT, Settings, get_settings
from src.models.common import ErrorDetail, EvidenceReference, OperationResult
from src.models.enums import EvidenceType, FailureSource

_MCP_PROTOCOL_VERSION = "2025-03-26"
_MAX_RESULT_BYTES = 512 * 1024
_ALLOWED_TOOLS = frozenset(
    {
        "browser_navigate",
        "browser_snapshot",
        "browser_take_screenshot",
    }
)


class PlaywrightMCPTransportError(RuntimeError):
    """Raised when the configured Playwright MCP server cannot respond safely."""


class PlaywrightMCPTransport(Protocol):
    """Minimal MCP transport contract used by the observation adapter."""

    def list_tools(self) -> set[str]:
        """Return the tools exposed by the connected server."""

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call an authorized observation-only MCP tool."""

    def close(self) -> None:
        """Release any transport resources."""


class StdioPlaywrightMCPTransport:
    """JSON-RPC stdio transport for the official ``@playwright/mcp`` server."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._timeout_seconds = settings.PLAYWRIGHT_TIMEOUT_MS / 1_000
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[str] = queue.Queue()
        self._request_id = 0
        self._advertised_tools: set[str] | None = None

    def list_tools(self) -> set[str]:
        """Initialize the server and return its declared tool names."""
        if self._advertised_tools is not None:
            return self._advertised_tools

        self._ensure_started()
        response = self._request("tools/list", {})
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise PlaywrightMCPTransportError(
                "Playwright MCP did not return a valid tools/list result."
            )

        self._advertised_tools = {
            tool["name"]
            for tool in result["tools"]
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
        return self._advertised_tools

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call an allowlisted browser-observation tool."""
        if name not in _ALLOWED_TOOLS:
            raise PlaywrightMCPTransportError(f"Playwright MCP tool is not permitted: {name}.")
        response = self._request("tools/call", {"name": name, "arguments": dict(arguments)})
        return response.get("result")

    def close(self) -> None:
        """Stop the short-lived MCP child process."""
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def _ensure_started(self) -> None:
        if self._process is not None:
            return

        if self._settings.PLAYWRIGHT_MCP_URL:
            raise PlaywrightMCPTransportError(
                "Remote Playwright MCP endpoints are not supported by this adapter."
            )

        try:
            arguments = shlex.split(self._settings.PLAYWRIGHT_MCP_ARGS, posix=False)
        except ValueError as error:
            raise PlaywrightMCPTransportError(
                "PLAYWRIGHT_MCP_ARGS contains invalid quoting."
            ) from error

        if self._settings.PLAYWRIGHT_HEADLESS and "--headless" not in arguments:
            arguments.append("--headless")
        if "--isolated" not in arguments:
            arguments.append("--isolated")

        command = self._settings.PLAYWRIGHT_MCP_COMMAND
        if os.name == "nt" and command.casefold() == "npx":
            command = "npx.cmd"

        try:
            self._process = subprocess.Popen(
                [command, *arguments],
                cwd=PROJECT_ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=_server_environment(),
            )
        except OSError as error:
            raise PlaywrightMCPTransportError(
                "Unable to start the configured Playwright MCP server."
            ) from error

        if self._process.stdout is None or self._process.stdin is None:
            self.close()
            raise PlaywrightMCPTransportError("Playwright MCP server did not expose stdio streams.")

        threading.Thread(
            target=self._read_stdout,
            daemon=True,
            name="playwright-mcp-stdout",
        ).start()
        self._request(
            "initialize",
            {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "testing-evaluation-agent", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            if line.strip():
                self._responses.put(line)

    def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self._ensure_process()
        self._request_id += 1
        request_id = self._request_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})

        while True:
            try:
                raw = self._responses.get(timeout=self._timeout_seconds)
            except queue.Empty as error:
                raise PlaywrightMCPTransportError("Playwright MCP server timed out.") from error

            try:
                response = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(response, dict):
                raise PlaywrightMCPTransportError("Playwright MCP returned an invalid response.")
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise PlaywrightMCPTransportError("Playwright MCP returned an error response.")
            return response

    def _notify(self, method: str, params: Mapping[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def _write(self, payload: Mapping[str, Any]) -> None:
        self._ensure_process()
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write(json.dumps(payload) + "\n")
        self._process.stdin.flush()

    def _ensure_process(self) -> None:
        if self._process is None or self._process.poll() is not None:
            raise PlaywrightMCPTransportError("Playwright MCP server is not running.")


class PlaywrightMCPAdapter:
    """Keep exploratory browser observations separate from test execution results."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: PlaywrightMCPTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    @property
    def is_enabled(self) -> bool:
        """Return whether Playwright MCP observations are active."""
        return self._settings.PLAYWRIGHT_MCP_ENABLED

    def take_snapshot(self, target_reference: str) -> OperationResult:
        """Navigate to a target and collect an accessibility snapshot as MCP evidence."""
        return self._collect_observation(
            target_reference,
            operation="take_snapshot",
            tool_name="browser_snapshot",
            description="Accessibility and page-structure observation; not execution evidence.",
        )

    def discover_locators(self, target_reference: str, description: str) -> OperationResult:
        """Collect a snapshot suitable for discovering locators for the requested behavior."""
        if not description.strip():
            return self._invalid_target_result(
                "discover_locators",
                "A locator description is required.",
            )
        return self._collect_observation(
            target_reference,
            operation="discover_locators",
            tool_name="browser_snapshot",
            description="Locator-discovery snapshot; not execution evidence.",
            requested_description=description,
        )

    def take_screenshot(self, target_reference: str) -> OperationResult:
        """Navigate to a target and collect a screenshot as MCP evidence."""
        return self._collect_observation(
            target_reference,
            operation="take_screenshot",
            tool_name="browser_take_screenshot",
            description="Browser screenshot observation; not execution evidence.",
        )

    @staticmethod
    def observation_evidence_type() -> EvidenceType:
        """Return the only evidence classification emitted by this adapter."""
        return EvidenceType.MCP_OBSERVATION

    def _collect_observation(
        self,
        target_reference: str,
        *,
        operation: str,
        tool_name: str,
        description: str,
        requested_description: str | None = None,
    ) -> OperationResult:
        if not self.is_enabled:
            return self._disabled_result(operation)
        if not _is_browser_url(target_reference):
            return self._invalid_target_result(
                operation,
                "Target reference must be an HTTP or HTTPS URL.",
            )

        try:
            transport = self._transport or StdioPlaywrightMCPTransport(self._settings)
            owns_transport = self._transport is None
            tools = transport.list_tools()
            required_tools = {"browser_navigate", tool_name}
            unavailable_tools = required_tools - tools
            if unavailable_tools:
                raise PlaywrightMCPTransportError(
                    "Playwright MCP does not advertise required tools: "
                    + ", ".join(sorted(unavailable_tools))
                )

            navigation = _bounded_result(
                transport.call_tool("browser_navigate", {"url": target_reference})
            )
            observation = _bounded_result(transport.call_tool(tool_name, {}))
            evidence = EvidenceReference(
                evidence_type=EvidenceType.MCP_OBSERVATION,
                title=f"Playwright MCP: {tool_name}",
                description=description,
                source=target_reference,
                metadata={
                    "tool": tool_name,
                    "requested_description": requested_description,
                },
            )
            return OperationResult(
                success=True,
                message="Playwright MCP observation collected. No test was executed.",
                metadata={
                    "observations": [evidence],
                    "results": {"browser_navigate": navigation, tool_name: observation},
                    "execution_performed": False,
                },
            )
        except (OSError, RuntimeError, ValueError) as error:
            return self._connection_result(operation, str(error))
        finally:
            if "owns_transport" in locals() and owns_transport:
                transport.close()

    def _disabled_result(self, operation: str) -> OperationResult:
        return OperationResult(
            success=False,
            message=f"Playwright MCP is disabled. No {operation} observation was collected.",
            errors=[
                ErrorDetail(
                    code="MCP_DISABLED",
                    message="PLAYWRIGHT_MCP_ENABLED is false. This is the default safe state.",
                    failure_source=FailureSource.CONFIGURATION,
                    blocking=False,
                    workflow_step=f"playwright_mcp_adapter.{operation}",
                )
            ],
        )

    def _invalid_target_result(self, operation: str, message: str) -> OperationResult:
        return OperationResult(
            success=False,
            message="Playwright MCP observation could not be collected.",
            errors=[
                ErrorDetail(
                    code="MCP_INVALID_TARGET",
                    message=message,
                    failure_source=FailureSource.CONFIGURATION,
                    workflow_step=f"playwright_mcp_adapter.{operation}",
                )
            ],
        )

    def _connection_result(self, operation: str, message: str) -> OperationResult:
        return OperationResult(
            success=False,
            message="Playwright MCP observation could not be collected.",
            errors=[
                ErrorDetail(
                    code="MCP_CONNECTION_FAILED",
                    message=message,
                    failure_source=FailureSource.MCP_CONNECTION,
                    workflow_step=f"playwright_mcp_adapter.{operation}",
                )
            ],
        )


def _server_environment() -> dict[str, str]:
    """Pass only runtime variables required to start the local MCP process."""
    retained = (
        "PATH",
        "SystemRoot",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOME",
        "APPDATA",
        "LOCALAPPDATA",
    )
    return {key: value for key in retained if (value := os.environ.get(key))}


def _is_browser_url(value: str) -> bool:
    """Return whether a target is a browser-reachable HTTP(S) address."""
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _bounded_result(result: Any) -> Any:
    """Reject oversized MCP observations before returning them as metadata."""
    serialized = json.dumps(result, ensure_ascii=True, default=str)
    if len(serialized.encode("utf-8")) > _MAX_RESULT_BYTES:
        raise ValueError("Playwright MCP response exceeded the configured size limit.")
    return result
