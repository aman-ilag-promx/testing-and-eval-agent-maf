"""Persistent manifest management for per-run workspace isolation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from src.config import PROJECT_ROOT
from src.models.runs import RunManifest
from src.tools.workspace_manager import WorkspaceManager

_MANIFEST_FILENAME = "manifest.json"


class RunManifestError(ValueError):
    """Base error for run manifest operations."""


class RunManifestNotFoundError(RunManifestError):
    """Raised when a manifest file cannot be located."""


class RunManifestCollisionError(RunManifestError):
    """Raised when a manifest already exists and save() would overwrite it."""


class RunManifestStore:
    """Save and load RunManifest records within their run workspace."""

    def __init__(self, workspace_manager: WorkspaceManager | None = None) -> None:
        self._workspace = workspace_manager or WorkspaceManager()

    def save(self, slug: str, manifest: RunManifest) -> Path:
        """Create the run workspace and persist the manifest; raises on collision."""
        run_dir = self._workspace.ensure_run_dir(slug, manifest.run_id)
        manifest_path = (run_dir / _MANIFEST_FILENAME).resolve()
        self._require_within(manifest_path)

        if manifest_path.exists():
            raise RunManifestCollisionError(
                f"Manifest already exists at {manifest_path}. "
                "Use update() to overwrite an existing manifest."
            )

        self._write_atomically(manifest_path, manifest.model_dump_json(indent=2))
        return manifest_path

    def update(self, slug: str, manifest: RunManifest) -> Path:
        """Overwrite an existing manifest; raises if not found."""
        run_dir = self._workspace.run_dir(slug, manifest.run_id)
        manifest_path = (run_dir / _MANIFEST_FILENAME).resolve()
        self._require_within(manifest_path)

        if not manifest_path.exists():
            raise RunManifestNotFoundError(
                f"No manifest at {manifest_path}. Use save() to create a new manifest."
            )

        self._write_atomically(manifest_path, manifest.model_dump_json(indent=2))
        return manifest_path

    def load(self, slug: str, run_id: UUID) -> RunManifest:
        """Load and validate the manifest for a specific run."""
        run_dir = self._workspace.run_dir(slug, run_id)
        manifest_path = (run_dir / _MANIFEST_FILENAME).resolve()
        self._require_within(manifest_path)

        if not manifest_path.exists():
            raise RunManifestNotFoundError(
                f"No manifest found for run {run_id} under slug {slug!r}."
            )

        raw = manifest_path.read_text(encoding="utf-8")
        try:
            return RunManifest.model_validate_json(raw)
        except ValidationError as error:
            raise RunManifestError(
                f"Manifest for run {run_id} failed validation: {error}"
            ) from error

    def list_run_ids(self, slug: str) -> list[UUID]:
        """Return the UUIDs of all runs registered under a target slug."""
        runs_root = self._workspace.target_dir(slug) / "runs"
        if not runs_root.exists():
            return []

        run_ids: list[UUID] = []
        for candidate in sorted(runs_root.iterdir()):
            if not candidate.is_dir():
                continue
            manifest_file = candidate / _MANIFEST_FILENAME
            if not manifest_file.exists():
                continue
            try:
                run_ids.append(UUID(candidate.name))
            except ValueError:
                pass

        return run_ids

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_within(path: Path) -> None:
        try:
            path.relative_to(PROJECT_ROOT.resolve())
        except ValueError as error:
            raise RunManifestError(
                f"Manifest path {path!r} escapes the repository root."
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
