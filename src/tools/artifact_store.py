"""Safe persistence for generated and approved repository artifacts."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from src.config import PROJECT_ROOT, Settings, get_settings
from src.models.common import (
    AgentBaseModel,
    ApprovalRecord,
    ArtifactMetadata,
    ArtifactReference,
    ErrorDetail,
    OperationResult,
)
from src.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    FailureSource,
)

ModelT = TypeVar("ModelT", bound=AgentBaseModel)

_METADATA_SUFFIX = ".metadata.json"


class ArtifactStoreError(ValueError):
    """Base error raised for invalid artifact-store operations."""


class ArtifactPathError(ArtifactStoreError):
    """Raised when an artifact path escapes or violates its managed location."""


class ArtifactCollisionError(ArtifactStoreError):
    """Raised when an artifact or its metadata sidecar already exists."""


class ArtifactNotFoundError(ArtifactStoreError):
    """Raised when a managed artifact or metadata sidecar does not exist."""


class ArtifactStore:
    """Persist and retrieve artifacts within configured repository directories."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the store with validated application settings."""

        self._settings = settings or get_settings()
        self._project_root = PROJECT_ROOT.resolve()

    def create_text(
        self,
        metadata: ArtifactMetadata,
        relative_path: Path,
        content: str,
        *,
        approval_record: ApprovalRecord | None = None,
    ) -> OperationResult:
        """Atomically create a UTF-8 text artifact and its metadata sidecar."""

        if not content:
            return self._failure(
                "ARTIFACT_CONTENT_EMPTY",
                "Artifact content must not be empty.",
            )

        return self._create_bytes(
            metadata,
            relative_path,
            content.encode("utf-8"),
            approval_record=approval_record,
        )

    def create_bytes(
        self,
        metadata: ArtifactMetadata,
        relative_path: Path,
        content: bytes,
        *,
        approval_record: ApprovalRecord | None = None,
    ) -> OperationResult:
        """Atomically create a binary artifact and its metadata sidecar."""

        if not content:
            return self._failure(
                "ARTIFACT_CONTENT_EMPTY",
                "Artifact content must not be empty.",
            )

        return self._create_bytes(
            metadata,
            relative_path,
            content,
            approval_record=approval_record,
        )

    def create_model(
        self,
        metadata: ArtifactMetadata,
        relative_path: Path,
        model: AgentBaseModel,
        *,
        approval_record: ApprovalRecord | None = None,
    ) -> OperationResult:
        """Atomically serialize a validated model and its artifact metadata."""

        content = model.model_dump_json(indent=2).encode("utf-8") + b"\n"
        return self._create_bytes(
            metadata,
            relative_path,
            content,
            approval_record=approval_record,
        )

    def read_text(self, reference: ArtifactReference) -> str:
        """Read a managed artifact as UTF-8 text after validating its metadata."""

        try:
            return self.read_bytes(reference).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ArtifactStoreError(
                f"Artifact is not valid UTF-8 text: {reference.path}."
            ) from error

    def read_bytes(self, reference: ArtifactReference) -> bytes:
        """Read a managed artifact as bytes after validating its metadata."""

        artifact_path = self._validated_reference_path(reference)
        self._read_matching_metadata(reference, artifact_path)
        return artifact_path.read_bytes()

    def read_model(self, reference: ArtifactReference, model_type: type[ModelT]) -> ModelT:
        """Read and validate a JSON artifact as the requested Pydantic model."""

        content = self.read_text(reference)
        try:
            return model_type.model_validate_json(content)
        except ValidationError as error:
            raise ArtifactStoreError(
                f"Artifact content does not match {model_type.__name__}: {reference.path}."
            ) from error

    def read_metadata(self, reference: ArtifactReference) -> ArtifactMetadata:
        """Read metadata for an artifact and verify that it matches the reference."""

        artifact_path = self._validated_reference_path(reference)
        return self._read_matching_metadata(reference, artifact_path)

    def list_artifacts(
        self,
        *,
        artifact_type: ArtifactType | None = None,
        status: ArtifactStatus | None = None,
    ) -> list[ArtifactReference]:
        """List valid managed artifacts, optionally filtered by type or status."""

        references: list[ArtifactReference] = []

        for metadata_path in self._iter_metadata_paths():
            metadata = self._load_metadata(metadata_path)
            artifact_path = self._artifact_path_for_metadata(metadata_path)

            if not artifact_path.is_file():
                raise ArtifactNotFoundError(
                    f"Artifact payload is missing for metadata: {metadata_path}."
                )

            relative_path = artifact_path.relative_to(self._project_root)
            self._validate_destination(
                metadata,
                relative_path,
                approval_record=None,
                require_approval_record=False,
            )

            if artifact_type is not None and metadata.artifact_type is not artifact_type:
                continue
            if status is not None and metadata.status is not status:
                continue

            references.append(metadata.to_reference(relative_path))

        return sorted(
            references,
            key=lambda reference: (
                reference.created_at,
                reference.path.as_posix() if reference.path is not None else "",
            ),
        )

    def update_metadata(
        self,
        reference: ArtifactReference,
        metadata: ArtifactMetadata,
        *,
        approval_record: ApprovalRecord | None = None,
    ) -> OperationResult:
        """Atomically update metadata without moving or replacing artifact content."""

        try:
            artifact_path = self._validated_reference_path(reference)
            current = self._read_matching_metadata(reference, artifact_path)
            self._validate_metadata_identity(current, metadata)

            relative_path = artifact_path.relative_to(self._project_root)
            self._validate_destination(metadata, relative_path, approval_record)
            self._validate_approval_transition(current, metadata, approval_record)
            self._atomic_write(
                self._metadata_path(artifact_path),
                self._metadata_bytes(metadata),
            )
        except (ArtifactStoreError, OSError) as error:
            return self._failure(
                "ARTIFACT_METADATA_UPDATE_FAILED",
                str(error),
                technical_details=repr(error),
            )

        return OperationResult(
            success=True,
            message=f"Updated metadata for artifact: {relative_path.as_posix()}.",
            artifact=metadata.to_reference(relative_path),
        )

    def _create_bytes(
        self,
        metadata: ArtifactMetadata,
        relative_path: Path,
        content: bytes,
        *,
        approval_record: ApprovalRecord | None,
    ) -> OperationResult:
        try:
            artifact_path = self._validate_destination(
                metadata,
                relative_path,
                approval_record,
            )
            metadata_path = self._metadata_path(artifact_path)

            if artifact_path.exists() or metadata_path.exists():
                raise ArtifactCollisionError(
                    f"Artifact path already exists: {relative_path.as_posix()}."
                )

            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(artifact_path, content)
            try:
                self._atomic_write(metadata_path, self._metadata_bytes(metadata))
            except OSError:
                artifact_path.unlink(missing_ok=True)
                raise
        except (ArtifactStoreError, OSError) as error:
            return self._failure(
                "ARTIFACT_CREATE_FAILED",
                str(error),
                technical_details=repr(error),
            )

        return OperationResult(
            success=True,
            message=f"Created artifact: {relative_path.as_posix()}.",
            artifact=metadata.to_reference(relative_path),
        )

    def _validate_destination(
        self,
        metadata: ArtifactMetadata,
        relative_path: Path,
        approval_record: ApprovalRecord | None,
        *,
        require_approval_record: bool = True,
    ) -> Path:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ArtifactPathError("Artifact paths must be safe repository-relative paths.")
        if not relative_path.name or relative_path.name in {".", ".."}:
            raise ArtifactPathError("Artifact path must identify a file.")
        if relative_path.name.endswith(_METADATA_SUFFIX):
            raise ArtifactPathError("Artifact paths must not use the metadata sidecar suffix.")

        artifact_path = (self._project_root / relative_path).resolve()
        self._require_within(artifact_path, self._project_root)

        allowed_roots = self._allowed_roots(metadata.artifact_type)
        if not any(self._is_within(artifact_path, root) for root in allowed_roots):
            roots = ", ".join(
                root.relative_to(self._project_root).as_posix() for root in allowed_roots
            )
            raise ArtifactPathError(
                f"{metadata.artifact_type.value} artifacts must remain under: {roots}."
            )

        if self._is_approved_destination(artifact_path):
            self._require_approved_metadata(
                metadata,
                approval_record,
                require_approval_record=require_approval_record,
            )

        return artifact_path

    def _allowed_roots(self, artifact_type: ArtifactType) -> tuple[Path, ...]:
        configured_roots: dict[ArtifactType, tuple[Path, ...]] = {
            ArtifactType.IMPLEMENTATION_PLAN: (
                self._settings.GENERATED_SPECS_DIR,
                self._settings.APPROVED_SPECS_DIR,
            ),
            ArtifactType.TEST_CASE_COLLECTION: (
                self._settings.GENERATED_SPECS_DIR,
                self._settings.APPROVED_SPECS_DIR,
            ),
            ArtifactType.TEST_CASE: (
                self._settings.GENERATED_SPECS_DIR,
                self._settings.APPROVED_SPECS_DIR,
            ),
            ArtifactType.PLAYWRIGHT_SCRIPT: (
                self._settings.GENERATED_TESTS_DIR,
                self._project_root / "tests/smoke",
                self._project_root / "tests/integration",
                self._project_root / "tests/ui",
            ),
            ArtifactType.EXECUTION_RESULT: (self._settings.REPORTS_DIR,),
            ArtifactType.EVALUATION_RESULT: (self._settings.EVAL_RESULTS_DIR,),
            ArtifactType.PLAN_COMPARISON: (self._settings.REPORTS_DIR,),
            ArtifactType.REPORT: (self._settings.REPORTS_DIR,),
            ArtifactType.SCREENSHOT: (self._settings.SCREENSHOTS_DIR,),
            ArtifactType.TRACE: (self._settings.TRACES_DIR,),
            ArtifactType.VIDEO: (self._settings.SCREENSHOTS_DIR,),
        }
        return tuple(root.resolve() for root in configured_roots[artifact_type])

    def _is_approved_destination(self, artifact_path: Path) -> bool:
        approved_roots = (
            self._settings.APPROVED_SPECS_DIR.resolve(),
            (self._project_root / "tests/smoke").resolve(),
            (self._project_root / "tests/integration").resolve(),
            (self._project_root / "tests/ui").resolve(),
        )
        return any(self._is_within(artifact_path, root) for root in approved_roots)

    @staticmethod
    def _require_approved_metadata(
        metadata: ArtifactMetadata,
        approval_record: ApprovalRecord | None,
        *,
        require_approval_record: bool,
    ) -> None:
        if (
            metadata.status is not ArtifactStatus.APPROVED
            or metadata.approval_status is not ApprovalStatus.APPROVED
        ):
            raise ArtifactStoreError("Approved destinations require approved artifact metadata.")
        if require_approval_record and (
            approval_record is None
            or approval_record.artifact_id != metadata.artifact_id
            or approval_record.status is not ApprovalStatus.APPROVED
            or approval_record.reviewer is None
            or approval_record.decided_at is None
        ):
            raise ArtifactStoreError(
                "Approved artifacts require a matching completed human approval record."
            )

    @staticmethod
    def _validate_approval_transition(
        current: ArtifactMetadata,
        updated: ArtifactMetadata,
        approval_record: ApprovalRecord | None,
    ) -> None:
        approval_changed = (
            current.approval_status is not updated.approval_status
            or current.status is not updated.status
            and updated.status in {ArtifactStatus.APPROVED, ArtifactStatus.REJECTED}
        )
        if not approval_changed:
            return

        if approval_record is None or approval_record.artifact_id != updated.artifact_id:
            raise ArtifactStoreError(
                "Approval lifecycle changes require a matching human approval record."
            )
        if approval_record.status is not updated.approval_status:
            raise ArtifactStoreError("Approval record status must match artifact approval_status.")
        if approval_record.reviewer is None or approval_record.decided_at is None:
            raise ArtifactStoreError("Approval lifecycle changes require a completed decision.")

    @staticmethod
    def _validate_metadata_identity(
        current: ArtifactMetadata,
        updated: ArtifactMetadata,
    ) -> None:
        immutable_fields = (
            ("artifact_id", current.artifact_id, updated.artifact_id),
            ("run_id", current.run_id, updated.run_id),
            ("artifact_type", current.artifact_type, updated.artifact_type),
            ("created_at", current.created_at, updated.created_at),
            ("created_by", current.created_by, updated.created_by),
        )
        changed_fields = [name for name, old, new in immutable_fields if old != new]
        if changed_fields:
            raise ArtifactStoreError(
                "Artifact metadata identity fields cannot change: "
                + ", ".join(changed_fields)
                + "."
            )
        if updated.updated_at < current.updated_at:
            raise ArtifactStoreError("updated_at must not move backwards.")

    def _validated_reference_path(self, reference: ArtifactReference) -> Path:
        if reference.path is None:
            raise ArtifactPathError("Artifact reference must include a path.")
        if reference.path.is_absolute() or ".." in reference.path.parts:
            raise ArtifactPathError("Artifact reference path must be repository-relative.")

        artifact_path = (self._project_root / reference.path).resolve()
        self._require_within(artifact_path, self._project_root)
        if not artifact_path.is_file():
            raise ArtifactNotFoundError(f"Artifact does not exist: {reference.path}.")

        allowed_roots = self._allowed_roots(reference.artifact_type)
        if not any(self._is_within(artifact_path, root) for root in allowed_roots):
            raise ArtifactPathError(
                f"Artifact path is not valid for {reference.artifact_type.value}."
            )
        return artifact_path

    def _read_matching_metadata(
        self,
        reference: ArtifactReference,
        artifact_path: Path,
    ) -> ArtifactMetadata:
        metadata = self._load_metadata(self._metadata_path(artifact_path))
        if metadata.artifact_id != reference.artifact_id:
            raise ArtifactStoreError("Artifact metadata does not match the reference ID.")
        if metadata.artifact_type is not reference.artifact_type:
            raise ArtifactStoreError("Artifact metadata does not match the reference type.")
        if metadata.status is not reference.status:
            raise ArtifactStoreError("Artifact metadata does not match the reference status.")
        return metadata

    @staticmethod
    def _metadata_path(artifact_path: Path) -> Path:
        return artifact_path.with_name(artifact_path.name + _METADATA_SUFFIX)

    @staticmethod
    def _artifact_path_for_metadata(metadata_path: Path) -> Path:
        if not metadata_path.name.endswith(_METADATA_SUFFIX):
            raise ArtifactPathError(f"Invalid metadata sidecar path: {metadata_path}.")
        artifact_name = metadata_path.name[: -len(_METADATA_SUFFIX)]
        return metadata_path.with_name(artifact_name)

    @staticmethod
    def _metadata_bytes(metadata: ArtifactMetadata) -> bytes:
        return metadata.model_dump_json(indent=2).encode("utf-8") + b"\n"

    @staticmethod
    def _load_metadata(metadata_path: Path) -> ArtifactMetadata:
        if not metadata_path.is_file():
            raise ArtifactNotFoundError(f"Artifact metadata does not exist: {metadata_path}.")
        try:
            return ArtifactMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValidationError) as error:
            raise ArtifactStoreError(f"Invalid artifact metadata: {metadata_path}.") from error

    def _iter_metadata_paths(self) -> Iterator[Path]:
        roots = {
            root for artifact_type in ArtifactType for root in self._allowed_roots(artifact_type)
        }
        for root in sorted(roots, key=lambda path: path.as_posix()):
            if root.is_dir():
                yield from sorted(root.rglob(f"*{_METADATA_SUFFIX}"))

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
            raise ArtifactPathError(f"Path must remain inside {root}: {path}.")

    @staticmethod
    def _failure(
        code: str,
        message: str,
        *,
        technical_details: str | None = None,
    ) -> OperationResult:
        return OperationResult(
            success=False,
            message=message,
            errors=[
                ErrorDetail(
                    code=code,
                    message=message,
                    failure_source=FailureSource.TOOL,
                    technical_details=technical_details,
                )
            ],
        )
