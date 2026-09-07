"""Validation and recording of reuse decisions for approved artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from src.config import PROJECT_ROOT
from src.models.enums import ArtifactStatus, BrowserName, TargetType
from src.models.reuse import ReusableAsset, ReuseCompatibilityCheck, ReuseDecision
from src.models.targets import TestTarget
from src.tools.workspace_manager import WorkspaceManager

_REUSE_DECISION_SUFFIX = ".reuse.json"
_ASSET_INDEX_FILENAME = "reuse-index.json"


class AssetReuseError(ValueError):
    """Base error for asset reuse operations."""


class AssetReuseValidationError(AssetReuseError):
    """Raised when a reuse compatibility check fails."""


class AssetReuse:
    """Validate and record reuse decisions for approved artifacts."""

    def __init__(self, workspace_manager: WorkspaceManager | None = None) -> None:
        self._workspace = workspace_manager or WorkspaceManager()

    def check_compatibility(
        self,
        asset: ReusableAsset,
        *,
        candidate_target: TestTarget,
        candidate_run_id: UUID,
        requested_scope_summary: str,
        requested_browser: BrowserName | None,
    ) -> ReuseCompatibilityCheck:
        """Evaluate all seven compatibility dimensions for a reuse candidate."""
        target_identity_match = asset.source_target_id == candidate_target.target_id
        target_type_match = asset.source_target_type == candidate_target.target_type
        environment_match = (
            candidate_target.environment is not None
            and asset.source_environment_classification
            == candidate_target.environment.classification
        )
        version_match = (
            asset.source_version_label is None
            or (
                candidate_target.version is not None
                and asset.source_version_label == candidate_target.version.version_label
            )
        )
        scope_match = (
            requested_scope_summary.strip().casefold()
            == asset.scope_summary.strip().casefold()
        )
        browser_match = (
            asset.source_browser is None
            or requested_browser is None
            or asset.source_browser == requested_browser
        )
        approval_status_confirmed = asset.approval_status in (
            ArtifactStatus.APPROVED,
            ArtifactStatus.REUSED,
        )

        return ReuseCompatibilityCheck(
            asset_id=asset.asset_id,
            candidate_target_id=candidate_target.target_id,
            candidate_run_id=candidate_run_id,
            target_identity_match=target_identity_match,
            target_type_match=target_type_match,
            environment_match=environment_match,
            version_match=version_match,
            scope_match=scope_match,
            browser_match=browser_match,
            approval_status_confirmed=approval_status_confirmed,
        )

    def record_decision(self, slug: str, run_id: UUID, decision: ReuseDecision) -> Path:
        """Persist a reuse decision beside the run workspace."""
        run_dir = self._workspace.run_dir(slug, run_id)
        if not run_dir.exists():
            raise AssetReuseError(
                f"Run workspace for {slug}/{run_id} does not exist. "
                "Ensure the run directory is created before recording reuse decisions."
            )
        filename = f"{decision.asset_id}{_REUSE_DECISION_SUFFIX}"
        dest = (run_dir / filename).resolve()
        self._require_within(dest)
        self._write_atomically(dest, decision.model_dump_json(indent=2))
        return dest

    def register_reusable_asset(self, slug: str, asset: ReusableAsset) -> Path:
        """Store a reusable approved asset in the target's reusable/ directory."""
        reusable_dir = self._workspace.reusable_dir(slug)
        reusable_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{asset.asset_id}.json"
        dest = (reusable_dir / filename).resolve()
        self._require_within(dest)

        if dest.exists():
            raise AssetReuseError(
                f"Reusable asset {asset.asset_id} is already registered. "
                "Assets are immutable once registered."
            )

        self._write_atomically(dest, asset.model_dump_json(indent=2))
        return dest

    def list_reusable_assets(self, slug: str) -> list[ReusableAsset]:
        """Return all validated reusable assets for a target slug."""
        reusable_dir = self._workspace.reusable_dir(slug)
        if not reusable_dir.exists():
            return []

        assets: list[ReusableAsset] = []
        for candidate in sorted(reusable_dir.glob("*.json")):
            try:
                raw = candidate.read_text(encoding="utf-8")
                assets.append(ReusableAsset.model_validate_json(raw))
            except (ValidationError, OSError):
                pass

        return assets

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_within(path: Path) -> None:
        try:
            path.relative_to(PROJECT_ROOT.resolve())
        except ValueError as error:
            raise AssetReuseError(
                f"Asset path {path!r} escapes the repository root."
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
