"""Persistent registry for registered test targets."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from src.config import PROJECT_ROOT
from src.models.targets import TestTarget
from src.tools.workspace_manager import WorkspaceManager

_TARGET_FILENAME = "target.json"


class TargetRegistryError(ValueError):
    """Base error for target registry operations."""


class TargetNotFoundError(TargetRegistryError):
    """Raised when a target cannot be located in the registry."""


class TargetCollisionError(TargetRegistryError):
    """Raised when a target file already exists and would be overwritten."""


class TargetRegistry:
    """Save, load, and list registered TestTarget records."""

    def __init__(self, workspace_manager: WorkspaceManager | None = None) -> None:
        self._workspace = workspace_manager or WorkspaceManager()

    def save(self, target: TestTarget) -> Path:
        """Persist a target to its workspace directory; raises on collision."""
        target_dir = self._workspace.ensure_target_dir(target.slug)
        target_path = (target_dir / _TARGET_FILENAME).resolve()
        self._require_within(target_path)

        if target_path.exists():
            raise TargetCollisionError(
                f"Target already registered at {target_path}. "
                "Use update() to overwrite an existing target."
            )

        self._write_atomically(target_path, target.model_dump_json(indent=2))
        return target_path

    def update(self, target: TestTarget) -> Path:
        """Overwrite an existing target record; raises if not found."""
        target_dir = self._workspace.target_dir(target.slug)
        target_path = (target_dir / _TARGET_FILENAME).resolve()
        self._require_within(target_path)

        if not target_path.exists():
            raise TargetNotFoundError(
                f"No target registered at {target_path}. Use save() to create a new target."
            )

        self._write_atomically(target_path, target.model_dump_json(indent=2))
        return target_path

    def load(self, slug: str) -> TestTarget:
        """Load and validate a target by its slug."""
        target_dir = self._workspace.target_dir(slug)
        target_path = (target_dir / _TARGET_FILENAME).resolve()
        self._require_within(target_path)

        if not target_path.exists():
            raise TargetNotFoundError(f"No target found for slug: {slug!r}")

        raw = target_path.read_text(encoding="utf-8")
        try:
            return TestTarget.model_validate_json(raw)
        except ValidationError as error:
            raise TargetRegistryError(
                f"Target record for slug {slug!r} failed validation: {error}"
            ) from error

    def load_by_id(self, target_id: UUID) -> TestTarget:
        """Load a target by its UUID, scanning all registered targets."""
        for target in self.list_all():
            if target.target_id == target_id:
                return target
        raise TargetNotFoundError(f"No target found with id: {target_id}")

    def list_all(self) -> list[TestTarget]:
        """Return all successfully validated targets from the workspace root."""
        workspaces_root = self._workspace._workspaces_root
        if not workspaces_root.exists():
            return []

        targets: list[TestTarget] = []
        for candidate in sorted(workspaces_root.iterdir()):
            if not candidate.is_dir():
                continue
            target_file = candidate / _TARGET_FILENAME
            if not target_file.exists():
                continue
            try:
                raw = target_file.read_text(encoding="utf-8")
                targets.append(TestTarget.model_validate_json(raw))
            except (ValidationError, OSError):
                # Corrupted or incomplete registrations are skipped, not surfaced
                pass

        return targets

    def exists(self, slug: str) -> bool:
        """Return True if a target with this slug is registered."""
        try:
            target_dir = self._workspace.target_dir(slug)
            return (target_dir / _TARGET_FILENAME).exists()
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_within(path: Path) -> None:
        try:
            path.relative_to(PROJECT_ROOT.resolve())
        except ValueError as error:
            raise TargetRegistryError(
                f"Target path {path!r} escapes the repository root."
            ) from error

    @staticmethod
    def _write_atomically(dest: Path, content: str) -> None:
        """Write content to a temp file and rename atomically."""
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
