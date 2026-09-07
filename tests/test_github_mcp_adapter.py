"""Tests for read-only GitHub MCP repository evidence collection."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.models.enums import EvidenceType, FailureSource
from src.tools.github_mcp_adapter import (
    GitHubMCPAdapter,
    GitHubMCPTransportError,
    HostedGitHubMCPTransport,
    StdioGitHubMCPTransport,
    parse_github_repository_url,
)


class FakeGitHubMCPTransport:
    """In-memory read-only MCP transport used to test adapter policy."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self) -> set[str]:
        return {
            "get_file_contents",
            "list_commits",
            "list_issues",
            "list_pull_requests",
            "search_code",
            "create_issue",
        }

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": name}]}


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(
        GITHUB_MCP_ENABLED=enabled,
        GITHUB_MCP_URL=None,
        GITHUB_MCP_COMMAND="github-mcp-server",
        GITHUB_MCP_ARGS="stdio",
    )


class FakeHTTPResponse:
    """Minimal context-managed response used for hosted MCP protocol tests."""

    def __init__(self, body: str, session_id: str | None = None) -> None:
        self._body = body.encode("utf-8")
        self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _hosted_settings() -> Settings:
    return Settings(
        GITHUB_MCP_ENABLED=True,
        GITHUB_MCP_URL="https://api.githubcopilot.com/mcp/readonly",
        GITHUB_MCP_TOKEN="configured-token",
    )


def test_disabled_adapter_never_calls_transport() -> None:
    transport = FakeGitHubMCPTransport()
    result = GitHubMCPAdapter(_settings(enabled=False), transport).collect_repository_evidence(
        "https://github.com/octocat/hello-world"
    )

    assert not result.success
    assert result.errors[0].code == "GITHUB_MCP_DISABLED"
    assert transport.calls == []


def test_collects_only_read_only_observations() -> None:
    transport = FakeGitHubMCPTransport()
    result = GitHubMCPAdapter(_settings(), transport).collect_repository_evidence(
        "https://github.com/octocat/hello-world.git",
        code_query="TODO",
    )

    assert result.success
    assert [name for name, _ in transport.calls] == [
        "get_file_contents",
        "list_commits",
        "list_issues",
        "list_pull_requests",
        "search_code",
    ]
    assert "create_issue" not in [name for name, _ in transport.calls]
    observations = result.metadata["observations"]
    assert all(item.evidence_type is EvidenceType.MCP_OBSERVATION for item in observations)
    assert result.metadata["execution_performed"] is False


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/octocat/hello-world", ("octocat", "hello-world")),
        ("https://github.com/octocat/hello-world.git", ("octocat", "hello-world")),
    ],
)
def test_parses_valid_github_repository_urls(url: str, expected: tuple[str, str]) -> None:
    assert parse_github_repository_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/octocat/hello-world",
        "http://github.com/octocat/hello-world",
        "https://github.com/octocat",
        "file:///repository",
    ],
)
def test_rejects_invalid_repository_urls(url: str) -> None:
    with pytest.raises(ValueError, match="Repository URL"):
        parse_github_repository_url(url)


def test_private_access_requires_environment_only_token() -> None:
    with pytest.raises(ValidationError, match="GITHUB_MCP_TOKEN"):
        Settings(
            GITHUB_MCP_ENABLED=True,
            GITHUB_MCP_COMMAND="github-mcp-server",
            GITHUB_MCP_ALLOW_PRIVATE_REPOSITORIES=True,
            GITHUB_MCP_TOKEN=None,
        )


def test_hosted_github_mcp_requires_a_nonblank_token() -> None:
    with pytest.raises(ValidationError, match="GITHUB_MCP_TOKEN"):
        Settings(
            GITHUB_MCP_ENABLED=True,
            GITHUB_MCP_URL="https://api.githubcopilot.com/mcp/readonly",
            GITHUB_MCP_TOKEN="",
        )


def test_hosted_transport_initializes_and_parses_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            FakeHTTPResponse('{"jsonrpc":"2.0","id":1,"result":{}}', "session-123"),
            FakeHTTPResponse(""),
            FakeHTTPResponse(
                "event: message\n"
                'data: {"jsonrpc":"2.0","id":2,"result":{"tools":['
                '{"name":"get_file_contents"},{"name":"list_issues"}]}}\n\n'
            ),
            FakeHTTPResponse(
                '{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text"}]}}'
            ),
        ]
    )
    requests: list[Any] = []

    def fake_urlopen(request: Any, *, timeout: float) -> FakeHTTPResponse:
        assert timeout == 30.0
        requests.append(request)
        return next(responses)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    transport = HostedGitHubMCPTransport(_hosted_settings())

    assert transport.list_tools() == {"get_file_contents", "list_issues"}
    assert transport.call_tool(
        "get_file_contents", {"owner": "octocat", "repo": "hello-world"}
    ) == {"content": [{"type": "text"}]}

    payloads = [json.loads(request.data.decode("utf-8")) for request in requests]
    assert [payload["method"] for payload in payloads] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert requests[0].get_header("Authorization").startswith("Bearer ")
    assert requests[1].get_header("Mcp-session-id") == "session-123"
    assert requests[2].get_header("X-mcp-readonly") == "true"
    assert requests[2].get_header("X-mcp-lockdown") == "true"
    assert requests[2].get_header("X-mcp-toolsets") == "repos,issues,pull_requests"


def test_hosted_transport_redacts_authentication_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, *, timeout: float) -> Any:
        raise HTTPError(request.full_url, 401, "Unauthorized", None, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(GitHubMCPTransportError, match="authentication was rejected"):
        HostedGitHubMCPTransport(_hosted_settings()).list_tools()


def test_connection_errors_are_structured_and_not_execution_results() -> None:
    class FailingTransport:
        def list_tools(self) -> set[str]:
            raise RuntimeError("token value must not appear")

        def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            raise AssertionError("must not be called")

    result = GitHubMCPAdapter(_settings(), FailingTransport()).collect_repository_evidence(
        "https://github.com/octocat/hello-world"
    )

    assert not result.success
    assert result.errors[0].failure_source is FailureSource.MCP_CONNECTION
    assert result.errors[0].code == "GITHUB_MCP_CONNECTION_FAILED"


def test_stdio_transport_rejects_write_tools_before_starting_server() -> None:
    transport = StdioGitHubMCPTransport(_settings())

    with pytest.raises(GitHubMCPTransportError, match="not permitted"):
        transport.call_tool("create_issue", {"owner": "octocat", "repo": "hello-world"})