"""Models for interactive testing conversation sessions."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from src.models.common import AgentBaseModel, utc_now
from src.models.enums import ConversationState, TargetType, TestCategory

_SECRET_LIKE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_\-]?key|bearer|credential|private[_\-]?key|conn[ection]*[_\-]?str)",
)

MessageRole = Literal["agent", "user", "system"]


class ConversationMessage(AgentBaseModel):
    """A single message within an interactive conversation session."""

    message_id: UUID = Field(default_factory=uuid4)
    role: MessageRole
    content: str = Field(min_length=1, max_length=20_000)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("content")
    @classmethod
    def reject_secret_like_content(cls, value: str) -> str:
        """Prevent accidental persistence of secret-like values in conversation history."""
        matches = _SECRET_LIKE.findall(value)
        if matches and len(value) > 200:
            raise ValueError(
                "Message content appears to contain a secret-like value. "
                "Store auth reference names only, not actual credentials."
            )
        return value


class ConversationSession(AgentBaseModel):
    """Resumable interactive session that tracks conversation state and collected target data."""

    session_id: UUID = Field(default_factory=uuid4)
    state: ConversationState = ConversationState.AWAITING_TARGET_TYPE

    # Progressively collected fields
    target_type: TargetType | None = None
    target_name: str | None = Field(default=None, max_length=255)
    target_id: UUID | None = None
    run_id: UUID | None = None

    repo_ref: str | None = Field(default=None, max_length=500)
    app_url: str | None = Field(default=None, max_length=2_000)
    environment_classification: str | None = Field(default=None, max_length=50)

    requested_capabilities: list[TestCategory] = Field(default_factory=list)

    # Auth reference names only — never actual secrets
    auth_references: list[str] = Field(default_factory=list)
    forbidden_operations: list[str] = Field(default_factory=list)

    reuse_previous_assets: bool | None = None
    scope_confirmed: bool = False

    pending_question: str | None = Field(default=None, max_length=2_000)
    warnings: list[str] = Field(default_factory=list)

    messages: list[ConversationMessage] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    resumed_at: datetime | None = None

    @field_validator("app_url")
    @classmethod
    def validate_app_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("app_url must start with http:// or https://.")
        return stripped

    @field_validator("auth_references")
    @classmethod
    def reject_secret_like_auth_names(cls, value: list[str]) -> list[str]:
        for ref in value:
            if _SECRET_LIKE.search(ref) and len(ref) > 30:
                raise ValueError(
                    "auth_references must contain reference names only, not actual secret values."
                )
        return value

    @model_validator(mode="after")
    def terminal_states_are_final(self) -> ConversationSession:
        """Warn if a terminal state has a pending question (defensive, not blocking)."""
        terminal = {
            ConversationState.COMPLETED,
            ConversationState.FAILED,
            ConversationState.CANCELLED,
        }
        if self.state in terminal and self.pending_question is not None:
            # Non-blocking: clear instead of raising, as sessions may be replayed
            object.__setattr__(self, "pending_question", None)
        return self

    def is_terminal(self) -> bool:
        """Return True when the session has reached a non-resumable end state."""
        return self.state in {
            ConversationState.COMPLETED,
            ConversationState.FAILED,
            ConversationState.CANCELLED,
        }

    def add_message(self, role: MessageRole, content: str) -> ConversationMessage:
        """Append a validated message and return it."""
        msg = ConversationMessage(role=role, content=content)
        self.messages.append(msg)
        return msg
