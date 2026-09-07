"""Playwright script-generation and execution models."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from src.models.common import (
    AgentBaseModel,
    ArtifactMetadata,
    ErrorDetail,
    EvidenceReference,
    WarningDetail,
)
from src.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    BrowserName,
    ExecutionStatus,
)
from src.models.test_cases import TestCase

PLAYWRIGHT_FILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.spec\.ts$")


def normalize_unique_strings(
    values: list[str],
    field_name: str,
) -> list[str]:
    """Normalize text values and remove case-insensitive duplicates."""

    normalized_values: list[str] = []
    seen_values: set[str] = set()

    for value in values:
        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError(f"{field_name} must not contain empty values.")

        comparison_value = normalized_value.casefold()

        if comparison_value not in seen_values:
            seen_values.add(comparison_value)
            normalized_values.append(normalized_value)

    return normalized_values


def validate_relative_repository_path(
    value: Path,
    field_name: str,
) -> Path:
    """Validate a safe repository-relative path."""

    if value.is_absolute():
        raise ValueError(f"{field_name} must be repository-relative.")

    if ".." in value.parts:
        raise ValueError(f"{field_name} must not contain parent-directory traversal.")

    return value


def normalize_datetime(
    value: datetime,
    field_name: str,
) -> datetime:
    """Require a timezone-aware datetime and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")

    return value.astimezone(UTC)


class PlaywrightGenerationConstraints(AgentBaseModel):
    """Constraints applied while generating Playwright scripts."""

    language: str = Field(
        default="typescript",
        pattern=r"^typescript$",
    )
    framework: str = Field(
        default="@playwright/test",
        pattern=r"^@playwright/test$",
    )
    prefer_accessible_locators: bool = True
    allow_css_locators: bool = True
    allow_xpath_locators: bool = False
    allow_fixed_delays: bool = False
    allow_destructive_actions: bool = False
    include_failure_screenshots: bool = True
    include_trace_support: bool = True
    maximum_scripts: int = Field(
        default=50,
        ge=1,
        le=500,
    )
    additional_rules: list[str] = Field(default_factory=list)

    @field_validator("additional_rules")
    @classmethod
    def validate_additional_rules(
        cls,
        value: list[str],
    ) -> list[str]:
        """Normalize additional script-generation rules."""

        return normalize_unique_strings(
            value,
            "additional_rules",
        )


class PlaywrightScriptGenerationRequest(AgentBaseModel):
    """Request to generate scripts from approved test cases."""

    run_id: UUID
    source_collection_id: UUID
    approved_test_cases: list[TestCase] = Field(min_length=1)
    constraints: PlaywrightGenerationConstraints = Field(
        default_factory=PlaywrightGenerationConstraints
    )
    output_directory: Path = Path("tests/generated")
    approval_reference_id: UUID
    additional_instructions: str | None = Field(
        default=None,
        max_length=8_000,
    )

    @field_validator("output_directory")
    @classmethod
    def validate_output_directory(
        cls,
        value: Path,
    ) -> Path:
        """Require generated scripts to remain in tests/generated."""

        validated_path = validate_relative_repository_path(
            value,
            "output_directory",
        )

        if validated_path.as_posix() != "tests/generated":
            raise ValueError(
                "Generated Playwright scripts must be written only to tests/generated."
            )

        return validated_path

    @model_validator(mode="after")
    def validate_test_case_approvals(self) -> Self:
        """Require human approval for every source test case."""

        unapproved_test_cases = [
            test_case.test_case_id
            for test_case in self.approved_test_cases
            if test_case.approval_status is not ApprovalStatus.APPROVED
        ]

        if unapproved_test_cases:
            identifiers = ", ".join(sorted(unapproved_test_cases))

            raise ValueError(
                f"Playwright scripts cannot be generated from unapproved test cases: {identifiers}."
            )

        return self

    @model_validator(mode="after")
    def validate_unique_test_cases(self) -> Self:
        """Require unique source test-case identifiers."""

        test_case_ids = [test_case.test_case_id for test_case in self.approved_test_cases]

        if len(test_case_ids) != len(set(test_case_ids)):
            raise ValueError("approved_test_cases must contain unique test-case IDs.")

        return self


class GeneratedPlaywrightScript(AgentBaseModel):
    """Generated Playwright TypeScript script awaiting approval."""

    metadata: ArtifactMetadata
    file_name: str
    relative_path: Path
    source_test_case_ids: list[str] = Field(min_length=1)
    content: str = Field(
        min_length=1,
        max_length=500_000,
    )
    generation_warnings: list[WarningDetail] = Field(default_factory=list)
    validation_errors: list[ErrorDetail] = Field(default_factory=list)

    @field_validator("file_name")
    @classmethod
    def validate_file_name(
        cls,
        value: str,
    ) -> str:
        """Require a safe Playwright specification file name."""

        normalized_value = value.strip()

        if not PLAYWRIGHT_FILE_PATTERN.fullmatch(normalized_value):
            raise ValueError(
                "file_name must end with .spec.ts and contain "
                "only letters, numbers, periods, underscores, "
                "and hyphens."
            )

        return normalized_value

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(
        cls,
        value: Path,
    ) -> Path:
        """Require scripts to remain under tests/generated."""

        validated_path = validate_relative_repository_path(
            value,
            "relative_path",
        )
        path_parts = validated_path.parts

        if len(path_parts) < 3 or path_parts[:2] != ("tests", "generated"):
            raise ValueError("Generated Playwright script paths must be under tests/generated.")

        if not PLAYWRIGHT_FILE_PATTERN.fullmatch(validated_path.name):
            raise ValueError("Generated Playwright script paths must use the .spec.ts extension.")

        return validated_path

    @field_validator("source_test_case_ids")
    @classmethod
    def validate_source_test_case_ids(
        cls,
        value: list[str],
    ) -> list[str]:
        """Normalize source test-case identifiers."""

        normalized_values = normalize_unique_strings(
            value,
            "source_test_case_ids",
        )

        return [test_case_id.upper() for test_case_id in normalized_values]

    @field_validator("content")
    @classmethod
    def validate_script_content(
        cls,
        value: str,
    ) -> str:
        """Require Playwright declarations and reject unsafe code."""

        required_fragments = (
            "@playwright/test",
            "test(",
            "expect(",
        )

        missing_fragments = [fragment for fragment in required_fragments if fragment not in value]

        if missing_fragments:
            missing = ", ".join(missing_fragments)

            raise ValueError(
                f"Generated Playwright content is missing required fragments: {missing}."
            )

        forbidden_fragments = (
            "page.waitForTimeout(",
            "process.env.PASSWORD",
            "process.env.API_KEY",
        )

        detected_forbidden_fragments = [
            fragment for fragment in forbidden_fragments if fragment in value
        ]

        if detected_forbidden_fragments:
            detected = ", ".join(detected_forbidden_fragments)

            raise ValueError(
                f"Generated Playwright content contains forbidden fragments: {detected}."
            )

        return value

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        """Validate artifact type, state, and file consistency."""

        if self.metadata.artifact_type is not ArtifactType.PLAYWRIGHT_SCRIPT:
            raise ValueError("Script metadata artifact_type must be playwright_script.")

        permitted_statuses = {
            ArtifactStatus.DRAFT,
            ArtifactStatus.AWAITING_APPROVAL,
            ArtifactStatus.APPROVED,
            ArtifactStatus.REJECTED,
            ArtifactStatus.SUPERSEDED,
            ArtifactStatus.INCOMPLETE,
        }

        if self.metadata.status not in permitted_statuses:
            raise ValueError("Generated Playwright script has an invalid artifact status.")

        if self.relative_path.name != self.file_name:
            raise ValueError("relative_path file name must match file_name.")

        return self

    @property
    def is_ready_for_execution(self) -> bool:
        """Return whether the script is validated and approved."""

        return (
            self.metadata.status is ArtifactStatus.APPROVED
            and self.metadata.approval_status is ApprovalStatus.APPROVED
            and self.metadata.validation_passed
            and not self.validation_errors
        )


class PlaywrightExecutionRequest(AgentBaseModel):
    """Approved request for separate Playwright execution."""

    run_id: UUID
    script_artifact_id: UUID
    script_path: Path
    approval_reference_id: UUID
    target_environment: str = Field(
        min_length=1,
        max_length=255,
    )
    base_url: str
    browser: BrowserName = BrowserName.CHROMIUM
    headless: bool = True
    retries: int = Field(
        default=0,
        ge=0,
        le=10,
    )
    workers: int = Field(
        default=1,
        ge=1,
        le=20,
    )
    timeout_ms: int = Field(
        default=30_000,
        ge=1,
        le=600_000,
    )
    capture_screenshot_on_failure: bool = True
    capture_trace_on_failure: bool = True
    capture_video_on_failure: bool = False
    live_execution_approved: bool = False
    destructive_execution_approved: bool = False

    @field_validator("script_path")
    @classmethod
    def validate_script_path(
        cls,
        value: Path,
    ) -> Path:
        """Require a script in an approved test directory."""

        validated_path = validate_relative_repository_path(
            value,
            "script_path",
        )

        allowed_directories = {
            "tests/smoke",
            "tests/integration",
            "tests/ui",
        }

        if validated_path.parent.as_posix() not in allowed_directories:
            raise ValueError(
                "Executable scripts must be located directly "
                "under tests/smoke, tests/integration, "
                "or tests/ui."
            )

        if not PLAYWRIGHT_FILE_PATTERN.fullmatch(validated_path.name):
            raise ValueError("Executable script names must use the .spec.ts extension.")

        return validated_path

    @field_validator("base_url")
    @classmethod
    def validate_base_url(
        cls,
        value: str,
    ) -> str:
        """Require a valid HTTP or HTTPS target URL."""

        normalized_value = value.strip()
        parsed_url = urlparse(normalized_value)

        if parsed_url.scheme not in {"http", "https"}:
            raise ValueError("base_url must use the HTTP or HTTPS scheme.")

        if not parsed_url.netloc:
            raise ValueError("base_url must contain a valid host.")

        return normalized_value.rstrip("/")

    @model_validator(mode="after")
    def validate_execution_approval(self) -> Self:
        """Require explicit approval before execution."""

        if not self.live_execution_approved:
            raise ValueError("Playwright execution requires explicit live execution approval.")

        return self


class PlaywrightExecutionResult(AgentBaseModel):
    """Result from a separately triggered Playwright execution."""

    metadata: ArtifactMetadata
    script_artifact_id: UUID
    script_path: Path
    status: ExecutionStatus
    exit_code: int | None = None
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = Field(
        default=None,
        ge=0,
    )
    passed_tests: int = Field(
        default=0,
        ge=0,
    )
    failed_tests: int = Field(
        default=0,
        ge=0,
    )
    skipped_tests: int = Field(
        default=0,
        ge=0,
    )
    timed_out_tests: int = Field(
        default=0,
        ge=0,
    )
    stdout: str = Field(
        default="",
        max_length=500_000,
    )
    stderr: str = Field(
        default="",
        max_length=500_000,
    )
    evidence: list[EvidenceReference] = Field(default_factory=list)
    warnings: list[WarningDetail] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)

    @field_validator("script_path")
    @classmethod
    def validate_result_script_path(
        cls,
        value: Path,
    ) -> Path:
        """Validate the executed repository-relative path."""

        return validate_relative_repository_path(
            value,
            "script_path",
        )

    @field_validator("started_at", "completed_at")
    @classmethod
    def validate_timestamps(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """Require timezone-aware execution timestamps."""

        if value is None:
            return None

        return normalize_datetime(
            value,
            "execution timestamp",
        )

    @model_validator(mode="after")
    def validate_result_metadata(self) -> Self:
        """Require execution-result artifact metadata."""

        if self.metadata.artifact_type is not ArtifactType.EXECUTION_RESULT:
            raise ValueError("Execution metadata artifact_type must be execution_result.")

        return self

    @model_validator(mode="after")
    def validate_result_consistency(self) -> Self:
        """Validate counts, exit code, timestamps, and state."""

        terminal_statuses = {
            ExecutionStatus.PASSED,
            ExecutionStatus.FAILED,
            ExecutionStatus.SKIPPED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.BLOCKED,
        }

        if self.status in terminal_statuses and self.completed_at is None:
            raise ValueError("A terminal execution status requires completed_at.")

        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at.")

        if self.status is ExecutionStatus.PASSED:
            if self.exit_code != 0:
                raise ValueError("A passed execution must have exit_code 0.")

            if self.failed_tests > 0 or self.timed_out_tests > 0:
                raise ValueError("A passed execution cannot contain failed or timed-out tests.")

        failure_statuses = {
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMED_OUT,
        }

        if self.status in failure_statuses and not self.errors:
            raise ValueError("A failed or timed-out execution must contain an error.")

        return self

    @property
    def total_tests(self) -> int:
        """Return the number of reported test outcomes."""

        return self.passed_tests + self.failed_tests + self.skipped_tests + self.timed_out_tests
