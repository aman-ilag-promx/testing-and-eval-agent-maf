"""Deterministic adapter for separately triggered Playwright execution."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from src.config import PROJECT_ROOT, Settings, get_settings
from src.models.common import (
    ApprovalRecord,
    ArtifactMetadata,
    ArtifactReference,
    ErrorDetail,
    EvidenceReference,
)
from src.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    EvidenceType,
    ExecutionStatus,
    FailureSource,
)
from src.models.playwright import PlaywrightExecutionRequest, PlaywrightExecutionResult
from src.tools.approval_store import ApprovalNotFoundError, ApprovalStore, ApprovalStoreError

_PLAYWRIGHT_FILE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*\.spec\.ts$"
)
_FALLBACK_RESULT_PATH: Final[Path] = Path("invalid-request.spec.ts")


class PlaywrightRunnerError(ValueError):
    """Base error raised for invalid Playwright runner operations."""


class PlaywrightRunnerPathError(PlaywrightRunnerError):
    """Raised when a requested script path violates safety constraints."""


class PlaywrightRunnerSafetyError(PlaywrightRunnerError):
    """Raised when execution safety settings or approval checks fail."""


class PlaywrightRunner:
    """Execute approved Playwright tests in approved repository test directories."""

    def __init__(
        self,
        settings: Settings | None = None,
        approval_store: ApprovalStore | None = None,
    ) -> None:
        """Initialize deterministic dependencies without starting any process."""

        self._settings = settings or get_settings()
        self._approval_store = approval_store or ApprovalStore()
        self._project_root = PROJECT_ROOT.resolve()

    def run(self, request: PlaywrightExecutionRequest) -> PlaywrightExecutionResult:
        """Run a single approved Playwright script with strict safety validation."""

        started_at = datetime.now(UTC)

        try:
            script_path = self._validate_request(request)
            command = self._build_command(request, script_path)
        except (PlaywrightRunnerError, ApprovalStoreError) as error:
            completed_at = datetime.now(UTC)
            return self._build_blocked_result(
                request=request,
                started_at=started_at,
                completed_at=completed_at,
                message=str(error),
                technical_details=repr(error),
            )

        try:
            completed_process = subprocess.run(
                command,
                cwd=self._project_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.timeout_ms / 1000,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            completed_at = datetime.now(UTC)
            stdout = self._coerce_process_stream(error.stdout)
            stderr = self._coerce_process_stream(error.stderr)
            return self._build_terminal_result(
                request=request,
                status=ExecutionStatus.TIMED_OUT,
                started_at=started_at,
                completed_at=completed_at,
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                error_code="PLAYWRIGHT_RUN_TIMEOUT",
                error_message=(
                    f"Playwright execution exceeded timeout after {request.timeout_ms} ms."
                ),
                technical_details=repr(error),
            )
        except FileNotFoundError as error:
            completed_at = datetime.now(UTC)
            return self._build_terminal_result(
                request=request,
                status=ExecutionStatus.BLOCKED,
                started_at=started_at,
                completed_at=completed_at,
                exit_code=None,
                stdout="",
                stderr="",
                error_code="PLAYWRIGHT_EXECUTABLE_NOT_FOUND",
                error_message="Playwright executable was not found.",
                technical_details=repr(error),
            )
        except OSError as error:
            completed_at = datetime.now(UTC)
            return self._build_terminal_result(
                request=request,
                status=ExecutionStatus.BLOCKED,
                started_at=started_at,
                completed_at=completed_at,
                exit_code=None,
                stdout="",
                stderr="",
                error_code="PLAYWRIGHT_PROCESS_LAUNCH_FAILED",
                error_message="Unable to start Playwright process.",
                technical_details=repr(error),
            )

        completed_at = datetime.now(UTC)
        status = (
            ExecutionStatus.PASSED if completed_process.returncode == 0 else ExecutionStatus.FAILED
        )

        execution_error: ErrorDetail | None = None
        if status is ExecutionStatus.FAILED:
            execution_error = ErrorDetail(
                code="PLAYWRIGHT_NONZERO_EXIT",
                message=(
                    "Playwright process exited with a nonzero exit code: "
                    f"{completed_process.returncode}."
                ),
                failure_source=FailureSource.TEST_SCRIPT,
                technical_details=(
                    f"command={command!r}; returncode={completed_process.returncode}"
                ),
            )

        parsed_counts = self._extract_test_counts(
            stdout=completed_process.stdout,
            stderr=completed_process.stderr,
        )

        metadata = ArtifactMetadata(
            run_id=request.run_id,
            artifact_type=ArtifactType.EXECUTION_RESULT,
            name=f"playwright-execution-{request.script_artifact_id}",
            status=self._artifact_status_for_execution_status(status),
            approval_status=ApprovalStatus.NOT_REQUIRED,
            skill_name="playwright-runner",
            parent_artifact_ids=[request.script_artifact_id],
            source_references=[request.script_path.as_posix()],
            validation_passed=(status is ExecutionStatus.PASSED),
        )

        result = PlaywrightExecutionResult(
            metadata=metadata,
            script_artifact_id=request.script_artifact_id,
            script_path=request.script_path,
            status=status,
            exit_code=completed_process.returncode,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=self._duration_ms(started_at, completed_at),
            passed_tests=parsed_counts["passed_tests"],
            failed_tests=parsed_counts["failed_tests"],
            skipped_tests=parsed_counts["skipped_tests"],
            timed_out_tests=parsed_counts["timed_out_tests"],
            stdout=completed_process.stdout,
            stderr=completed_process.stderr,
            evidence=self._collect_evidence(request, started_at, completed_at),
            errors=[] if execution_error is None else [execution_error],
        )

        return result

    def _validate_request(self, request: PlaywrightExecutionRequest) -> Path:
        self._validate_execution_settings()
        self._validate_request_safety_flags(request)

        script_path = self._validate_script_path(request.script_path)
        self._validate_approval(request)

        return script_path

    def _validate_execution_settings(self) -> None:
        if not self._settings.REQUIRE_SCRIPT_APPROVAL:
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because REQUIRE_SCRIPT_APPROVAL is disabled."
            )

        if self._settings.APP_ENV == "production":
            raise PlaywrightRunnerSafetyError(
                "Execution against production is not permitted by the runner."
            )

        if not self._settings.ALLOW_LIVE_TEST_EXECUTION:
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because ALLOW_LIVE_TEST_EXECUTION is disabled."
            )

        if self._settings.ALLOW_DESTRUCTIVE_TESTS:
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because ALLOW_DESTRUCTIVE_TESTS is enabled."
            )

        if self._settings.ADO_MCP_ENABLED:
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because ADO MCP must remain disabled."
            )

    @staticmethod
    def _validate_request_safety_flags(request: PlaywrightExecutionRequest) -> None:
        if not request.live_execution_approved:
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because live_execution_approved is false."
            )

        if request.destructive_execution_approved:
            raise PlaywrightRunnerSafetyError(
                "Destructive execution is not permitted by the runner."
            )

    def _validate_script_path(self, script_path: Path) -> Path:
        if script_path.is_absolute():
            raise PlaywrightRunnerPathError("Executable script paths must not be absolute.")

        if ".." in script_path.parts:
            raise PlaywrightRunnerPathError(
                "Executable script paths must not contain parent-directory traversal."
            )

        if script_path.parts[:2] == ("tests", "generated"):
            raise PlaywrightRunnerPathError("Execution from tests/generated is not allowed.")

        if script_path.parent.as_posix() not in {
            "tests/smoke",
            "tests/integration",
            "tests/ui",
        }:
            raise PlaywrightRunnerPathError(
                "Executable scripts must be located in tests/smoke, tests/integration, or tests/ui."
            )

        if not _PLAYWRIGHT_FILE_PATTERN.fullmatch(script_path.name):
            raise PlaywrightRunnerPathError(
                "Executable script names must match *.spec.ts TypeScript test files."
            )

        unresolved_path = self._project_root / script_path

        if self._contains_symbolic_link(unresolved_path):
            raise PlaywrightRunnerPathError(
                "Executable scripts must not use symbolic links in their path."
            )

        resolved_path = unresolved_path.resolve()

        if not self._is_within(resolved_path, self._project_root):
            raise PlaywrightRunnerPathError(
                "Executable script path must remain inside the repository root."
            )

        if not resolved_path.is_file():
            raise PlaywrightRunnerPathError(
                f"Executable script file does not exist: {script_path.as_posix()}."
            )

        return resolved_path

    def _validate_approval(self, request: PlaywrightExecutionRequest) -> ApprovalRecord:
        reference = ArtifactReference(
            artifact_id=request.script_artifact_id,
            artifact_type=ArtifactType.PLAYWRIGHT_SCRIPT,
            name=request.script_path.name,
            path=request.script_path,
            status=ArtifactStatus.APPROVED,
            created_at=datetime.now(UTC),
        )

        try:
            record = self._approval_store.read(reference)
        except ApprovalNotFoundError as error:
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because no script approval record was found."
            ) from error

        if record.status is not ApprovalStatus.APPROVED:
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because the script approval record is not approved."
            )

        if record.approval_id != request.approval_reference_id:
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because approval_reference_id does "
                "not match the script approval record."
            )

        if record.reviewer is None or record.decided_at is None:
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because the script approval decision is incomplete."
            )

        return record

    def _build_command(self, request: PlaywrightExecutionRequest, script_path: Path) -> list[str]:
        relative_script_path = script_path.relative_to(self._project_root).as_posix()
        command = [
            *self._resolve_playwright_command_prefix(),
            "test",
            relative_script_path,
            "--project",
            request.browser.value,
            "--retries",
            str(request.retries),
            "--workers",
            str(request.workers),
            "--timeout",
            str(request.timeout_ms),
        ]

        if not request.headless:
            command.append("--headed")

        return command

    def _resolve_playwright_command_prefix(self) -> list[str]:
        local_windows_executable = self._project_root / "node_modules" / ".bin" / "playwright.cmd"
        if local_windows_executable.is_file():
            return [str(local_windows_executable)]

        local_posix_executable = self._project_root / "node_modules" / ".bin" / "playwright"
        if local_posix_executable.is_file():
            return [str(local_posix_executable)]

        package_json_path = self._project_root / "package.json"
        if not package_json_path.is_file():
            raise PlaywrightRunnerSafetyError(
                "Execution is blocked because package.json is required for Playwright fallback."
            )

        return ["npx", "--no-install", "playwright"]

    @staticmethod
    def _artifact_status_for_execution_status(status: ExecutionStatus) -> ArtifactStatus:
        if status is ExecutionStatus.PASSED:
            return ArtifactStatus.PASSED
        if status in {ExecutionStatus.FAILED, ExecutionStatus.TIMED_OUT}:
            return ArtifactStatus.FAILED
        if status is ExecutionStatus.BLOCKED:
            return ArtifactStatus.INCOMPLETE
        return ArtifactStatus.EXECUTED

    @staticmethod
    def _duration_ms(started_at: datetime, completed_at: datetime) -> int:
        delta = completed_at - started_at
        return max(int(delta.total_seconds() * 1000), 0)

    def _collect_evidence(
        self,
        request: PlaywrightExecutionRequest,
        started_at: datetime,
        completed_at: datetime,
    ) -> list[EvidenceReference]:
        evidence: list[EvidenceReference] = []

        json_report = self._project_root / "reports" / "playwright-results.json"
        if self._is_fresh_execution_artifact(json_report, started_at, completed_at):
            evidence.append(
                EvidenceReference(
                    evidence_type=EvidenceType.REPORT,
                    title="Playwright JSON report",
                    source="playwright",
                    artifact_id=request.script_artifact_id,
                    path=json_report.relative_to(self._project_root),
                )
            )

        html_report = self._project_root / "playwright-report" / "index.html"
        if self._is_fresh_execution_artifact(html_report, started_at, completed_at):
            evidence.append(
                EvidenceReference(
                    evidence_type=EvidenceType.REPORT,
                    title="Playwright HTML report",
                    source="playwright",
                    artifact_id=request.script_artifact_id,
                    path=html_report.relative_to(self._project_root),
                )
            )

        return evidence

    @staticmethod
    def _coerce_process_stream(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _build_blocked_result(
        self,
        *,
        request: PlaywrightExecutionRequest,
        started_at: datetime,
        completed_at: datetime,
        message: str,
        technical_details: str,
    ) -> PlaywrightExecutionResult:
        return self._build_terminal_result(
            request=request,
            status=ExecutionStatus.BLOCKED,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=None,
            stdout="",
            stderr="",
            error_code="PLAYWRIGHT_EXECUTION_BLOCKED",
            error_message=message,
            technical_details=technical_details,
        )

    def _build_terminal_result(
        self,
        *,
        request: PlaywrightExecutionRequest,
        status: ExecutionStatus,
        started_at: datetime,
        completed_at: datetime,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        error_code: str,
        error_message: str,
        technical_details: str,
    ) -> PlaywrightExecutionResult:
        parsed_counts = self._extract_test_counts(stdout=stdout, stderr=stderr)

        metadata = ArtifactMetadata(
            run_id=request.run_id,
            artifact_type=ArtifactType.EXECUTION_RESULT,
            name=f"playwright-execution-{request.script_artifact_id}",
            status=self._artifact_status_for_execution_status(status),
            approval_status=ApprovalStatus.NOT_REQUIRED,
            skill_name="playwright-runner",
            parent_artifact_ids=[request.script_artifact_id],
            source_references=[request.script_path.as_posix()],
            validation_passed=False,
        )

        return PlaywrightExecutionResult(
            metadata=metadata,
            script_artifact_id=request.script_artifact_id,
            script_path=self._safe_result_script_path(request.script_path),
            status=status,
            exit_code=exit_code,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=self._duration_ms(started_at, completed_at),
            passed_tests=parsed_counts["passed_tests"],
            failed_tests=parsed_counts["failed_tests"],
            skipped_tests=parsed_counts["skipped_tests"],
            timed_out_tests=parsed_counts["timed_out_tests"],
            stdout=stdout,
            stderr=stderr,
            evidence=[],
            errors=[
                ErrorDetail(
                    code=error_code,
                    message=error_message,
                    failure_source=FailureSource.TOOL,
                    technical_details=technical_details,
                )
            ],
        )

    @staticmethod
    def _extract_test_counts(stdout: str, stderr: str) -> dict[str, int]:
        combined_output = f"{stdout}\n{stderr}"

        def find_count(pattern: str) -> int:
            match = re.search(pattern, combined_output, flags=re.IGNORECASE)
            if match is None:
                return 0
            return int(match.group(1))

        return {
            "passed_tests": find_count(r"(\d+)\s+passed\b"),
            "failed_tests": find_count(r"(\d+)\s+failed\b"),
            "skipped_tests": find_count(r"(\d+)\s+skipped\b"),
            "timed_out_tests": find_count(r"(\d+)\s+timed\s+out\b"),
        }

    @staticmethod
    def _safe_result_script_path(script_path: Path) -> Path:
        if script_path.is_absolute() or ".." in script_path.parts:
            return _FALLBACK_RESULT_PATH
        return script_path

    @staticmethod
    def _contains_symbolic_link(path: Path) -> bool:
        current = path
        while True:
            if current.exists() and current.is_symlink():
                return True

            if current.parent == current:
                return False

            current = current.parent

    @staticmethod
    def _is_fresh_execution_artifact(
        candidate_path: Path,
        started_at: datetime,
        completed_at: datetime,
    ) -> bool:
        if not candidate_path.is_file():
            return False

        modified_at = datetime.fromtimestamp(candidate_path.stat().st_mtime, tz=UTC)
        return started_at <= modified_at <= completed_at

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True
