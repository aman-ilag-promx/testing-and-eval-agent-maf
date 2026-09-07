"""Conversational agent managing interactive session state and delegation."""

from __future__ import annotations

from uuid import UUID

from src.agents.model_client import ModelClient
from src.models.conversation import ConversationSession
from src.models.enums import ConversationState
from src.tools.session_store import SessionStore, SessionNotFoundError
from src.tools.workspace_manager import WorkspaceManager
from src.workflows.conversation_workflow import ConversationWorkflow, ConversationWorkflowError


class ConversationAgentError(RuntimeError):
    """Raised when the conversation agent cannot proceed."""


class ConversationAgent:
    """Frontend-independent agent for interactive testing session management.

    All methods return structured data.
    Terminal rendering is the caller's responsibility.
    """

    def __init__(
        self,
        model_client: ModelClient | None = None,
        conversation_workflow: ConversationWorkflow | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self._workflow = conversation_workflow or ConversationWorkflow(model_client=model_client)
        self._session_store = session_store or SessionStore()

    def start_session(self, target_type_hint: str | None = None) -> ConversationSession:
        """Create a new session, optionally with a pre-filled target type answer."""
        session = self._workflow.start()

        if target_type_hint:
            session = self._workflow.advance(session, target_type_hint)

        return session

    def resume_session(self, session_id: UUID) -> ConversationSession:
        """Resume an existing session by its UUID."""
        try:
            return self._workflow.resume(session_id)
        except SessionNotFoundError as exc:
            raise ConversationAgentError(str(exc)) from exc
        except ConversationWorkflowError as exc:
            raise ConversationAgentError(str(exc)) from exc

    def respond(self, session_id: UUID, user_input: str) -> ConversationSession:
        """Process a user message and return the updated session."""
        try:
            session = self._session_store.load(session_id)
        except SessionNotFoundError as exc:
            raise ConversationAgentError(str(exc)) from exc

        try:
            return self._workflow.advance(session, user_input)
        except ConversationWorkflowError as exc:
            raise ConversationAgentError(str(exc)) from exc

    def list_sessions(self) -> list[UUID]:
        """Return the UUIDs of all persisted sessions."""
        return self._session_store.list_session_ids()

    def get_session(self, session_id: UUID) -> ConversationSession:
        """Load a session by its UUID."""
        try:
            return self._session_store.load(session_id)
        except SessionNotFoundError as exc:
            raise ConversationAgentError(str(exc)) from exc
