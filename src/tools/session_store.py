"""Safe persistence and resumption of interactive conversation sessions."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from src.config import PROJECT_ROOT
from src.models.conversation import ConversationSession
from src.tools.workspace_manager import WorkspaceManager

_SESSION_SUFFIX = ".session.json"


class SessionStoreError(ValueError):
    """Base error for session store operations."""


class SessionNotFoundError(SessionStoreError):
    """Raised when no session file exists for the given session ID."""


class SessionStore:
    """Persist and resume ConversationSession records without storing secrets."""

    def __init__(self, workspace_manager: WorkspaceManager | None = None) -> None:
        self._workspace = workspace_manager or WorkspaceManager()

    def save(self, session: ConversationSession) -> Path:
        """Persist a session; overwrites any existing record for the same session ID."""
        sessions_dir = self._workspace.ensure_sessions_dir()
        dest = (sessions_dir / f"{session.session_id}{_SESSION_SUFFIX}").resolve()
        self._require_within(dest)
        self._write_atomically(dest, session.model_dump_json(indent=2))
        return dest

    def load(self, session_id: UUID) -> ConversationSession:
        """Load and validate a session by its UUID."""
        sessions_dir = self._workspace.sessions_dir()
        path = (sessions_dir / f"{session_id}{_SESSION_SUFFIX}").resolve()
        self._require_within(path)

        if not path.exists():
            raise SessionNotFoundError(f"No session found for ID: {session_id}")

        raw = path.read_text(encoding="utf-8")
        try:
            return ConversationSession.model_validate_json(raw)
        except ValidationError as error:
            raise SessionStoreError(
                f"Session {session_id} failed validation: {error}"
            ) from error

    def list_session_ids(self) -> list[UUID]:
        """Return UUIDs of all persisted sessions."""
        sessions_dir = self._workspace.sessions_dir()
        if not sessions_dir.exists():
            return []

        session_ids: list[UUID] = []
        for candidate in sorted(sessions_dir.glob(f"*{_SESSION_SUFFIX}")):
            stem = candidate.name[: -len(_SESSION_SUFFIX)]
            try:
                session_ids.append(UUID(stem))
            except ValueError:
                pass

        return session_ids

    def delete(self, session_id: UUID) -> None:
        """Remove a persisted session record."""
        sessions_dir = self._workspace.sessions_dir()
        path = (sessions_dir / f"{session_id}{_SESSION_SUFFIX}").resolve()
        self._require_within(path)

        if not path.exists():
            raise SessionNotFoundError(f"No session found for ID: {session_id}")

        path.unlink()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_within(path: Path) -> None:
        try:
            path.relative_to(PROJECT_ROOT.resolve())
        except ValueError as error:
            raise SessionStoreError(
                f"Session path {path!r} escapes the repository root."
            ) from error

    @staticmethod
    def _write_atomically(dest: Path, content: str) -> None:
        dir_ = dest.parent
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_path, dest)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
