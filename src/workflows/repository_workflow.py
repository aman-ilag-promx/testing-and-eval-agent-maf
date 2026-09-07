"""Approval-gated workflow for repository registration and safe command discovery."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from src.models.common import ErrorDetail, OperationResult, WarningDetail, utc_now
from src.models.enums import FailureSource, WorkflowOutcome, WorkflowStage
from src.models.targets import TestTarget
from src.models.workflow import WorkflowResult, WorkflowState
from src.tools.github_mcp_adapter import GitHubMCPAdapter
from src.tools.repo_validator import RepoValidator
from src.tools.target_registry import TargetCollisionError, TargetRegistry
from src.tools.workspace_manager import WorkspaceManager
from src.workflows.approval_workflow import ApprovalWorkflow


class RepositoryWorkflowError(ValueError):
    """Base error raised by the repository workflow."""


class RepositoryWorkflow:
    """Approval-gated registration and validation of a local repository target."""

    def __init__(
        self,
        repo_validator: RepoValidator | None = None,
        target_registry: TargetRegistry | None = None,
        approval_workflow: ApprovalWorkflow | None = None,
        workspace_manager: WorkspaceManager | None = None,
        github_mcp_adapter: GitHubMCPAdapter | None = None,
    ) -> None:
        self._repo_validator = repo_validator or RepoValidator()
        self._target_registry = target_registry or TargetRegistry()
        self._approval_workflow = approval_workflow or ApprovalWorkflow()
        self._workspace_manager = workspace_manager or WorkspaceManager()
        self._github_mcp_adapter = github_mcp_adapter or GitHubMCPAdapter()

    def collect_github_evidence(
        self,
        repository_url: str,
        *,
        code_query: str | None = None,
    ) -> OperationResult:
        """Collect read-only GitHub MCP observations for a remote repository."""
        return self._github_mcp_adapter.collect_repository_evidence(
            repository_url,
            code_query=code_query,
        )

    def register_and_validate(self, target: TestTarget, *, repo_path: Path) -> WorkflowResult:
        """Register the target and validate its repository structure.

        Does not clone, execute, or modify the repository.
        Requires human approval before any discovered commands may be run.
        """
        errors: list[ErrorDetail] = []
        warnings: list[WarningDetail] = []
        now = utc_now()
        workflow_id = uuid4()

        # 1. Validate the repo path structure
        validation_result = self._repo_validator.validate(repo_path)
        warnings.extend(validation_result.warnings)

        if not validation_result.success:
            errors.extend(validation_result.errors)
            return self._failed_result(workflow_id, errors, warnings, now)

        # 2. Persist the target registration
        try:
            self._target_registry.save(target)
        except TargetCollisionError:
            self._target_registry.update(target)
        except Exception as exc:
            errors.append(ErrorDetail(
                code="TARGET_REGISTRATION_FAILED",
                message=f"Could not register target: {exc}",
                failure_source=FailureSource.TOOL,
                workflow_step="repository_workflow.register",
                technical_details=repr(exc),
            ))
            return self._failed_result(workflow_id, errors, warnings, now)

        # 3. Warn about discoverable commands requiring approval
        discovered = validation_result.metadata.get("discoverable_commands", {})
        command_names = list(discovered.get("commands", {}).keys())
        if command_names:
            warnings.append(WarningDetail(
                code="COMMANDS_REQUIRE_APPROVAL",
                message=(
                    f"Discovered {len(command_names)} command(s) requiring approval "
                    f"before execution: {', '.join(command_names)}"
                ),
            ))

        state = WorkflowState(
            workflow_id=workflow_id,
            current_stage=WorkflowStage.INITIALIZED,
            outcome=WorkflowOutcome.SUCCESS,
            target_id=target.target_id,
            warnings=warnings,
            errors=errors,
            created_at=now,
            updated_at=now,
        )

        return WorkflowResult(
            workflow_state=state,
            outcome=WorkflowOutcome.SUCCESS,
            message=(
                f"Target {target.name!r} registered and repository validated. "
                "No commands were executed. Approval is required before running any command."
            ),
            warnings=warnings,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _failed_result(
        workflow_id: UUID,
        errors: list[ErrorDetail],
        warnings: list[WarningDetail],
        now: datetime,
    ) -> WorkflowResult:
        state = WorkflowState(
            workflow_id=workflow_id,
            current_stage=WorkflowStage.FAILED,
            outcome=WorkflowOutcome.FAILURE,
            warnings=warnings,
            errors=errors,
            created_at=now,
            updated_at=now,
        )
        return WorkflowResult(
            workflow_state=state,
            outcome=WorkflowOutcome.FAILURE,
            message="Repository registration or validation failed. See errors for details.",
            warnings=warnings,
            errors=errors,
        )
