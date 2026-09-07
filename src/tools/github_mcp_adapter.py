"""Read-only GitHub MCP evidence collection with a least-privilege stdio boundary."""

from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlparse

from src.config import Settings, get_settings
from src.models.common import ErrorDetail, EvidenceReference, OperationResult, WarningDetail
from src.models.enums import EvidenceType, FailureSource

_READ_ONLY_TOOLS = frozenset(
    {
        "get_file_contents",
        "list_commits",
        "list_issues",
        "list_pull_requests",
        "search_code",
    }
)
_MAX_RESULT_BYTES = 512 * 1024
_MCP_PROTOCOL_VERSION = "2025-03-26"
_HTTP_ACCEPT = "application/json, text/event-stream"


class GitHubMCPTransportError(RuntimeError):
    """Raised when a configured GitHub MCP server cannot return a valid response."""


class GitHubMCPTransport(Protocol):
    """Minimal transport contract used by the read-only GitHub adapter."""

    def list_tools(self) -> set[str]:
        """Return the tools advertised by the connected MCP server."""

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call one already-authorized MCP tool."""

    def close(self) -> None:
        """Release any transport resources."""


class StdioGitHubMCPTransport:
    """JSON-RPC stdio transport for a configured official GitHub MCP server."""

    def __init__(self, settings: Settings, timeout_seconds: float = 30.0) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds
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
            raise GitHubMCPTransportError("GitHub MCP did not return a valid tools/list result.")

        self._advertised_tools = {
            tool["name"]
            for tool in result["tools"]
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
        return self._advertised_tools

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call a discovered MCP tool using standard tools/call JSON-RPC."""
        if name not in _READ_ONLY_TOOLS:
            raise GitHubMCPTransportError(f"GitHub MCP tool is not permitted: {name}.")
        response = self._request("tools/call", {"name": name, "arguments": dict(arguments)})
        return response.get("result")

    def close(self) -> None:
        """Stop the child MCP server when this transport is no longer needed."""
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

        command = self._settings.GITHUB_MCP_COMMAND.strip()
        if not command:
            raise GitHubMCPTransportError("GITHUB_MCP_COMMAND is not configured.")

        try:
            args = shlex.split(self._settings.GITHUB_MCP_ARGS, posix=False)
        except ValueError as error:
            raise GitHubMCPTransportError("GITHUB_MCP_ARGS contains invalid quoting.") from error

        environment = _server_environment(self._settings)
        try:
            self._process = subprocess.Popen(
                [command, *args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=environment,
            )
        except OSError as error:
            raise GitHubMCPTransportError(
                "Unable to start the configured GitHub MCP server."
            ) from error

        if self._process.stdout is None or self._process.stdin is None:
            self.close()
            raise GitHubMCPTransportError("GitHub MCP server did not expose stdio streams.")

        threading.Thread(
            target=self._read_stdout,
            daemon=True,
            name="github-mcp-stdout",
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
                raise GitHubMCPTransportError("GitHub MCP server timed out.") from error

            try:
                response = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if not isinstance(response, dict):
                raise GitHubMCPTransportError("GitHub MCP returned an invalid response.")
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise GitHubMCPTransportError("GitHub MCP returned an error response.")
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
            raise GitHubMCPTransportError("GitHub MCP server is not running.")


class HostedGitHubMCPTransport:
    """Streamable HTTP transport for GitHub's hosted read-only MCP endpoint."""

    def __init__(self, settings: Settings) -> None:
        if settings.GITHUB_MCP_URL is None or settings.GITHUB_MCP_TOKEN is None:
            raise GitHubMCPTransportError("Hosted GitHub MCP URL and token are required.")

        self._url = settings.GITHUB_MCP_URL
        self._token = settings.GITHUB_MCP_TOKEN.get_secret_value()
        self._timeout_seconds = settings.GITHUB_MCP_TIMEOUT_SECONDS
        self._request_id = 0
        self._session_id: str | None = None
        self._advertised_tools: set[str] | None = None
        self._initialized = False

    def list_tools(self) -> set[str]:
        """Initialize the remote server and return its advertised tool names."""
        if self._advertised_tools is not None:
            return self._advertised_tools

        self._initialize()
        result = self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise GitHubMCPTransportError(
                "Hosted GitHub MCP returned an invalid tools/list result."
            )

        self._advertised_tools = {
            tool["name"]
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
        return self._advertised_tools

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call an allowlisted read-only tool through the hosted MCP endpoint."""
        if name not in _READ_ONLY_TOOLS:
            raise GitHubMCPTransportError(f"GitHub MCP tool is not permitted: {name}.")
        self._initialize()
        return self._request("tools/call", {"name": name, "arguments": dict(arguments)})

    def close(self) -> None:
        """Release local session state; the hosted endpoint requires no process cleanup."""
        self._session_id = None

    def _initialize(self) -> None:
        if self._initialized:
            return

        self._request(
            "initialize",
            {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "testing-evaluation-agent", "version": "0.1.0"},
            },
            include_protocol_version=False,
        )
        self._notify("notifications/initialized", {})
        self._initialized = True

    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        include_protocol_version: bool = True,
    ) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        response = self._post(payload, include_protocol_version=include_protocol_version)
        if response.get("id") != request_id:
            raise GitHubMCPTransportError("Hosted GitHub MCP returned an unexpected response ID.")
        if "error" in response:
            raise GitHubMCPTransportError("Hosted GitHub MCP returned an error response.")
        result = response.get("result")
        if not isinstance(result, dict):
            raise GitHubMCPTransportError("Hosted GitHub MCP returned an invalid result.")
        return result

    def _notify(self, method: str, params: Mapping[str, Any]) -> None:
        self._post(
            {"jsonrpc": "2.0", "method": method, "params": dict(params)},
            include_protocol_version=True,
        )

    def _post(
        self,
        payload: Mapping[str, Any],
        *,
        include_protocol_version: bool,
    ) -> dict[str, Any]:
        headers = {
            "Accept": _HTTP_ACCEPT,
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "X-MCP-Toolsets": "repos,issues,pull_requests",
            "X-MCP-Readonly": "true",
            "X-MCP-Lockdown": "true",
        }
        if include_protocol_version:
            headers["MCP-Protocol-Version"] = _MCP_PROTOCOL_VERSION
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        request = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self._session_id = session_id
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise GitHubMCPTransportError(
                    "Hosted GitHub MCP authentication was rejected."
                ) from error
            raise GitHubMCPTransportError("Hosted GitHub MCP returned an HTTP error.") from error
        except (OSError, TimeoutError) as error:
            raise GitHubMCPTransportError("Unable to connect to hosted GitHub MCP.") from error

        if not body.strip():
            return {}
        return _parse_mcp_response(body)


class GitHubMCPAdapter:
    """Collect bounded, read-only GitHub MCP observations for repository analysis."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: GitHubMCPTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    @property
    def is_enabled(self) -> bool:
        """Return whether GitHub MCP evidence collection is enabled."""
        return self._settings.GITHUB_MCP_ENABLED

    def collect_repository_evidence(
        self,
        repository_url: str,
        *,
        code_query: str | None = None,
        include_commits: bool = True,
        include_issues: bool = True,
        include_pull_requests: bool = True,
    ) -> OperationResult:
        """Collect read-only metadata and optional repository evidence."""
        if not self.is_enabled:
            return self._disabled_result()

        try:
            owner, repository = parse_github_repository_url(repository_url)
            transport = self._transport or self._create_transport()
            owns_transport = self._transport is None
            tools = transport.list_tools()
            unsupported = _READ_ONLY_TOOLS - tools
            if "get_file_contents" not in tools:
                return self._connection_result(
                    "GitHub MCP does not advertise the required get_file_contents tool."
                )

            observations: list[EvidenceReference] = []
            results: dict[str, Any] = {}
            calls: list[tuple[str, dict[str, Any]]] = [
                ("get_file_contents", {"owner": owner, "repo": repository}),
            ]
            if include_commits:
                calls.append(("list_commits", {"owner": owner, "repo": repository, "perPage": 20}))
            if include_issues:
                calls.append(("list_issues", {"owner": owner, "repo": repository, "perPage": 20}))
            if include_pull_requests:
                calls.append(
                    ("list_pull_requests", {"owner": owner, "repo": repository, "perPage": 20})
                )
            if code_query:
                calls.append(
                    (
                        "search_code",
                        {"query": f"{code_query} repo:{owner}/{repository}", "perPage": 20},
                    )
                )

            for tool_name, arguments in calls:
                if tool_name not in tools:
                    continue
                result = _bounded_result(transport.call_tool(tool_name, arguments))
                results[tool_name] = result
                observations.append(
                    EvidenceReference(
                        evidence_type=EvidenceType.MCP_OBSERVATION,
                        title=f"GitHub MCP: {tool_name}",
                        description="Read-only repository observation; not execution evidence.",
                        source=repository_url,
                        metadata={"tool": tool_name, "owner": owner, "repository": repository},
                    )
                )

            warnings = []
            if unsupported:
                warnings.append(
                    _warning(
                        "GITHUB_MCP_TOOLS_UNAVAILABLE",
                        "Some optional read-only GitHub MCP tools are unavailable: "
                        + ", ".join(sorted(unsupported)),
                    )
                )

            return OperationResult(
                success=True,
                message="Read-only GitHub MCP repository evidence collected.",
                warnings=warnings,
                metadata={
                    "repository": f"{owner}/{repository}",
                    "observations": observations,
                    "results": results,
                    "execution_performed": False,
                },
            )
        except (GitHubMCPTransportError, OSError, RuntimeError, ValueError) as error:
            return self._connection_result(str(error))
        finally:
            if "owns_transport" in locals() and owns_transport:
                transport.close()

    @staticmethod
    def observation_evidence_type() -> EvidenceType:
        """Return the non-execution evidence type used by this adapter."""
        return EvidenceType.MCP_OBSERVATION

    def _disabled_result(self) -> OperationResult:
        return OperationResult(
            success=False,
            message="GitHub MCP is disabled. Enable it only for read-only repository evidence.",
            errors=[
                ErrorDetail(
                    code="GITHUB_MCP_DISABLED",
                    message="GITHUB_MCP_ENABLED is false. No GitHub MCP call was made.",
                    failure_source=FailureSource.CONFIGURATION,
                    blocking=False,
                    workflow_step="github_mcp_adapter.collect_repository_evidence",
                )
            ],
        )

    def _create_transport(self) -> GitHubMCPTransport:
        if self._settings.GITHUB_MCP_URL:
            return HostedGitHubMCPTransport(self._settings)
        return StdioGitHubMCPTransport(self._settings)

    def _connection_result(self, message: str) -> OperationResult:
        return OperationResult(
            success=False,
            message="GitHub MCP repository evidence could not be collected.",
            errors=[
                ErrorDetail(
                    code="GITHUB_MCP_CONNECTION_FAILED",
                    message=_redact(message, self._settings.GITHUB_MCP_TOKEN),
                    failure_source=FailureSource.MCP_CONNECTION,
                    workflow_step="github_mcp_adapter.collect_repository_evidence",
                )
            ],
        )


def parse_github_repository_url(repository_url: str) -> tuple[str, str]:
    """Validate a GitHub repository URL and return its owner and repository name."""
    parsed = urlparse(repository_url.strip())
    if parsed.scheme != "https" or parsed.netloc.casefold() != "github.com":
        raise ValueError("Repository URL must be an HTTPS GitHub repository URL.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise ValueError("Repository URL must contain exactly an owner and repository name.")
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not owner or not repository:
        raise ValueError("Repository owner and name must not be empty.")
    return owner, repository


def _server_environment(settings: Settings) -> dict[str, str]:
    """Pass only runtime essentials and the optional GitHub token to the MCP process."""
    retained = ("PATH", "SystemRoot", "TEMP", "TMP", "USERPROFILE", "HOME")
    environment = {key: value for key in retained if (value := os.environ.get(key))}
    if settings.GITHUB_MCP_TOKEN is not None:
        environment["GITHUB_PERSONAL_ACCESS_TOKEN"] = settings.GITHUB_MCP_TOKEN.get_secret_value()
    return environment


def _bounded_result(result: Any) -> Any:
    """Reject oversized MCP replies before they are persisted as evidence metadata."""
    serialized = json.dumps(result, ensure_ascii=True, default=str)
    if len(serialized.encode("utf-8")) > _MAX_RESULT_BYTES:
        raise ValueError("GitHub MCP response exceeded the configured size limit.")
    return result


def _parse_mcp_response(body: str) -> dict[str, Any]:
    """Parse the JSON or single JSON-RPC event emitted by Streamable HTTP MCP."""
    candidate = body.strip()
    data_lines = [line[5:].strip() for line in candidate.splitlines() if line.startswith("data:")]
    if data_lines:
        candidate = "\n".join(data_lines)

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise GitHubMCPTransportError("Hosted GitHub MCP returned invalid JSON.") from error
    if not isinstance(parsed, dict):
        raise GitHubMCPTransportError("Hosted GitHub MCP returned an invalid response.")
    return parsed


def _redact(message: str, token: object | None = None) -> str:
    """Avoid exposing credential-like values through structured error output."""
    redacted = message.replace("GITHUB_PERSONAL_ACCESS_TOKEN", "GitHub token")
    if token is not None and hasattr(token, "get_secret_value"):
        secret = token.get_secret_value()
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _warning(code: str, message: str) -> WarningDetail:
    return WarningDetail(code=code, message=message)