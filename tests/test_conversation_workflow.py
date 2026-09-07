"""Tests for conversation data routing used by the CLI test pipeline."""

from src.models.conversation import ConversationSession
from src.workflows.conversation_workflow import _merge_extracted


def test_github_repository_url_is_stored_as_a_repository_reference() -> None:
    """GitHub URLs must reach the read-only GitHub MCP evidence workflow."""

    session = ConversationSession()

    _merge_extracted(session, {"target_url": "https://github.com/octocat/hello-world/"})

    assert session.repo_ref == "https://github.com/octocat/hello-world"
    assert session.app_url is None