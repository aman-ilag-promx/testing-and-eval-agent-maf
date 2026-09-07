"""Deterministic workspace directory management for per-target and per-run isolation."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from src.config import PROJECT_ROOT, Settings, get_settings

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")

# Sub-directories created under each run workspace
_RUN_SUBDIRS = (
    "request",
    "discovery",
    "generated-test-cases",
    "approved-test-cases",
    "generated-scripts",
    "approved-scripts",
    "execution-results",
    "screenshots",
    "traces",
    "evaluations",
    "comparisons",
    "reports",
)


class WorkspaceError(ValueError):
    """Base error raised for invalid workspace operations."""


class WorkspacePathError(WorkspaceError):
    """Raised when a path escapes the repository workspace boundary."""


class WorkspaceManager:
    """Create and resolve per-target and per-run workspace directories."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._workspaces_root = (
            self._settings.WORKSPACES_DIR
            if self._settings.WORKSPACES_DIR.is_absolute()
            else (PROJECT_ROOT / self._settings.WORKSPACES_DIR).resolve()
        )

    # ------------------------------------------------------------------
    # Target-level
    # ------------------------------------------------------------------

    def target_dir(self, slug: str) -> Path:
        """Return the workspace directory for a target slug (does not create it)."""
        self._validate_slug(slug)
        path = (self._workspaces_root / slug).resolve()
        self._require_within(path, self._workspaces_root)
        return path

    def ensure_target_dir(self, slug: str) -> Path:
        """Create and return the workspace directory for a target slug."""
        path = self.target_dir(slug)
        path.mkdir(parents=True, exist_ok=True)
        reusable = path / "reusable"
        reusable.mkdir(exist_ok=True)
        return path

    def reusable_dir(self, slug: str) -> Path:
        """Return the reusable assets directory for a target slug."""
        path = (self.target_dir(slug) / "reusable").resolve()
        self._require_within(path, self._workspaces_root)
        return path

    # ------------------------------------------------------------------
    # Run-level
    # ------------------------------------------------------------------

    def run_dir(self, slug: str, run_id: UUID) -> Path:
        """Return the run directory path (does not create it)."""
        self._validate_slug(slug)
        path = (self.target_dir(slug) / "runs" / str(run_id)).resolve()
        self._require_within(path, self._workspaces_root)
        return path

    def ensure_run_dir(self, slug: str, run_id: UUID) -> Path:
        """Create and return the run directory with all standard sub-directories."""
        path = self.run_dir(slug, run_id)
        path.mkdir(parents=True, exist_ok=True)
        for sub in _RUN_SUBDIRS:
            (path / sub).mkdir(exist_ok=True)
        return path

    def run_subdir(self, slug: str, run_id: UUID, sub: str) -> Path:
        """Return a specific run sub-directory path, validated against the allowed list."""
        if sub not in _RUN_SUBDIRS:
            raise WorkspaceError(
                f"Unknown run sub-directory: {sub!r}. "
                f"Allowed: {', '.join(_RUN_SUBDIRS)}"
            )
        path = (self.run_dir(slug, run_id) / sub).resolve()
        self._require_within(path, self._workspaces_root)
        return path

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def sessions_dir(self) -> Path:
        """Return the conversation sessions directory."""
        sessions_root = (
            self._settings.CONVERSATION_SESSIONS_DIR
            if self._settings.CONVERSATION_SESSIONS_DIR.is_absolute()
            else (PROJECT_ROOT / self._settings.CONVERSATION_SESSIONS_DIR).resolve()
        )
        self._require_within(sessions_root, PROJECT_ROOT)
        return sessions_root

    def ensure_sessions_dir(self) -> Path:
        """Create and return the sessions directory."""
        path = self.sessions_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_slug(slug: str) -> None:
        if not _SLUG_PATTERN.match(slug):
            raise WorkspaceError(
                f"Invalid slug: {slug!r}. Must be 3–63 lowercase alphanumeric characters or hyphens."
            )

    @staticmethod
    def _require_within(path: Path, root: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as error:
            raise WorkspacePathError(
                f"Path {path!r} escapes the workspace boundary {root!r}."
            ) from error
