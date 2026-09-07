"""Safe persistence and retrieval of explicit human approval records."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from src.config import PROJECT_ROOT
from src.models.common import ApprovalRecord, ArtifactReference
from src.models.enums import ApprovalStatus

_APPROVAL_SUFFIX = ".approval.json"


class ApprovalStoreError(ValueError):
    """Base error raised for invalid approval-store operations."""


class ApprovalPathError(ApprovalStoreError):
    """Raised when an approval path escapes the repository boundary."""


class ApprovalNotFoundError(ApprovalStoreError):
    """Raised when an approval record does not exist."""


class ApprovalCollisionError(ApprovalStoreError):
    """Raised when an approval record already exists."""


class ApprovalValidationError(ApprovalStoreError):
    """Raised when an approval record is incomplete or inconsistent."""


class ApprovalTransitionError(ApprovalStoreError):
    """Raised when an approval decision violates lifecycle rules."""


class ApprovalStore:
    """Persist explicit human approval records beside managed artifacts."""

    def __init__(self) -> None:
        """Initialize the store within the repository root."""
        self._project_root = PROJECT_ROOT.resolve()

    def save(
        self,
        reference: ArtifactReference,
        record: ApprovalRecord,
    ) -> Path:
        """Persist a completed approval record without overwriting a decision."""
        artifact_path = self._validated_artifact_path(reference)
        self._validate_record(reference, record)

        approval_path = self._approval_path(artifact_path)
        self._require_within(approval_path, self._project_root)

        if approval_path.exists():
            raise ApprovalCollisionError(
                f"Approval record already exists for artifact: {reference.artifact_id}."
            )

        approval_content = record.model_dump_json(indent=2).encode("utf-8") + b"\n"
        self._atomic_write(approval_path, approval_content)

        return approval_path.relative_to(self._project_root)

    def read(self, reference: ArtifactReference) -> ApprovalRecord:
        """Read and validate the approval record for an artifact."""
        artifact_path = self._validated_artifact_path(reference)
        approval_path = self._approval_path(artifact_path)
        self._require_within(approval_path, self._project_root)

        if not approval_path.is_file():
            raise ApprovalNotFoundError(
                f"Approval record does not exist for artifact: {reference.artifact_id}."
            )

        try:
            content = approval_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ApprovalStoreError(
                f"Unable to read approval record for artifact: {reference.artifact_id}."
            ) from error

        try:
            record = ApprovalRecord.model_validate_json(content)
        except ValidationError as error:
            raise ApprovalValidationError(
                f"Approval record is invalid for artifact: {reference.artifact_id}."
            ) from error

        self._validate_record(reference, record)
        return record

    def exists(self, reference: ArtifactReference) -> bool:
        """Return whether an approval record exists for an artifact."""
        artifact_path = self._validated_artifact_path(reference)
        approval_path = self._approval_path(artifact_path)
        self._require_within(approval_path, self._project_root)
        return approval_path.is_file()

    def replace(
        self,
        reference: ArtifactReference,
        record: ApprovalRecord,
    ) -> Path:
        """Replace a pending record with one completed human decision."""
        artifact_path = self._validated_artifact_path(reference)
        approval_path = self._approval_path(artifact_path)
        self._require_within(approval_path, self._project_root)

        if not approval_path.is_file():
            raise ApprovalNotFoundError(
                f"Approval record does not exist for artifact: {reference.artifact_id}."
            )

        current_record = self.read(reference)
        self._validate_record(reference, record)
        self._validate_transition(current_record, record)

        approval_content = record.model_dump_json(indent=2).encode("utf-8") + b"\n"
        self._atomic_write(approval_path, approval_content)

        return approval_path.relative_to(self._project_root)

    def delete_pending(self, reference: ArtifactReference) -> None:
        """Delete only an undecided pending approval record."""
        artifact_path = self._validated_artifact_path(reference)
        approval_path = self._approval_path(artifact_path)
        self._require_within(approval_path, self._project_root)

        current_record = self.read(reference)

        if current_record.status is not ApprovalStatus.PENDING:
            raise ApprovalTransitionError("A completed approval decision must not be deleted.")

        try:
            approval_path.unlink()
        except OSError as error:
            raise ApprovalStoreError(
                f"Unable to delete pending approval record for artifact: {reference.artifact_id}."
            ) from error

    def _validated_artifact_path(
        self,
        reference: ArtifactReference,
    ) -> Path:
        if reference.path is None:
            raise ApprovalPathError("Artifact reference must include a repository-relative path.")

        if reference.path.is_absolute():
            raise ApprovalPathError("Artifact reference path must not be absolute.")

        if ".." in reference.path.parts:
            raise ApprovalPathError("Artifact reference path must not contain traversal segments.")

        if not reference.path.name:
            raise ApprovalPathError("Artifact reference path must identify a file.")

        artifact_path = (self._project_root / reference.path).resolve()

        self._require_within(artifact_path, self._project_root)

        if artifact_path.is_symlink():
            raise ApprovalPathError("Approval records must not target symbolic links.")

        if not artifact_path.is_file():
            raise ApprovalNotFoundError(f"Artifact does not exist: {reference.path.as_posix()}.")

        return artifact_path

    @staticmethod
    def _validate_record(
        reference: ArtifactReference,
        record: ApprovalRecord,
    ) -> None:
        if record.artifact_id != reference.artifact_id:
            raise ApprovalValidationError(
                "Approval record artifact_id must match the artifact reference."
            )

        if record.status is ApprovalStatus.PENDING:
            if record.reviewer is not None:
                raise ApprovalValidationError(
                    "A pending approval record must not contain a reviewer."
                )

            if record.decided_at is not None:
                raise ApprovalValidationError(
                    "A pending approval record must not contain decided_at."
                )

            return

        if record.reviewer is None:
            raise ApprovalValidationError("A completed approval decision requires a reviewer.")

        if not record.reviewer.strip():
            raise ApprovalValidationError("Approval reviewer must not be empty or whitespace.")

        if record.decided_at is None:
            raise ApprovalValidationError("A completed approval decision requires decided_at.")

        if record.decided_at.tzinfo is None or record.decided_at.utcoffset() is None:
            raise ApprovalValidationError("Approval decided_at must be timezone-aware.")

    @staticmethod
    def _validate_transition(
        current: ApprovalRecord,
        updated: ApprovalRecord,
    ) -> None:
        if current.artifact_id != updated.artifact_id:
            raise ApprovalTransitionError("Approval record artifact identity must not change.")

        if current.status is not ApprovalStatus.PENDING:
            raise ApprovalTransitionError("A completed approval decision must not be replaced.")

        if updated.status is ApprovalStatus.PENDING:
            raise ApprovalTransitionError(
                "Replacement must complete the pending approval decision."
            )

        if updated.reviewer is None or updated.decided_at is None:
            raise ApprovalTransitionError(
                "Replacement requires a completed human approval decision."
            )

    @staticmethod
    def _approval_path(artifact_path: Path) -> Path:
        return artifact_path.with_name(artifact_path.name + _APPROVAL_SUFFIX)

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False

        return True

    @classmethod
    def _require_within(cls, path: Path, root: Path) -> None:
        if not cls._is_within(path, root):
            raise ApprovalPathError(f"Path must remain inside the repository root: {path}.")

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
