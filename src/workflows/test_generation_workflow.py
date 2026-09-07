"""Deterministic workflow for generating draft test-case collections."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from src.models.common import (
    ArtifactMetadata,
    ArtifactReference,
    ErrorDetail,
    WarningDetail,
    utc_now,
)
from src.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    AutomationSuitability,
    FailureSource,
    TestCategory,
    TestPriority,
    WorkflowOutcome,
    WorkflowStage,
)
from src.models.test_cases import TestCase, TestCaseCollection, TestCaseGenerationRequest, TestStep
from src.models.workflow import WorkflowResult, WorkflowState, WorkflowTransition
from src.tools.artifact_store import ArtifactStore
from src.tools.skill_loader import SkillLoader, SkillLoaderError
from src.workflows.approval_workflow import ApprovalWorkflow


class TestGenerationWorkflow:
    """Generate draft test cases and stop at checkpoint A for human approval."""

    def __init__(
        self,
        artifact_store: ArtifactStore | None = None,
        skill_loader: SkillLoader | None = None,
        approval_workflow: ApprovalWorkflow | None = None,
    ) -> None:
        """Initialize deterministic dependencies."""

        self._artifact_store = artifact_store or ArtifactStore()
        self._skill_loader = skill_loader or SkillLoader()
        self._approval_workflow = approval_workflow or ApprovalWorkflow()

    def run(self, request: TestCaseGenerationRequest) -> WorkflowResult:
        """Generate a TestCaseCollection and move to awaiting approval."""

        now = utc_now()
        errors: list[ErrorDetail] = []
        warnings: list[WarningDetail] = []

        try:
            self._skill_loader.load("generate-test-cases")
        except SkillLoaderError as error:
            errors.append(
                ErrorDetail(
                    code="SKILL_LOAD_FAILED",
                    message="Unable to load generate-test-cases skill definition.",
                    failure_source=FailureSource.SKILL,
                    workflow_step="test_generation.load_skill",
                    technical_details=repr(error),
                )
            )
            return self._failed_result(request, errors, now, "Skill loading failed.")

        secret_like = self._contains_secret_like_input(
            request.implementation_input.original_user_request,
            request.implementation_input.implementation_plan or "",
        )
        if secret_like:
            errors.append(
                ErrorDetail(
                    code="INPUT_CONTAINS_SECRET_LIKE_VALUE",
                    message=(
                        "Input appears to contain credential-like text. "
                        "Remove secrets before generation."
                    ),
                    failure_source=FailureSource.TOOL,
                    workflow_step="test_generation.validate_input",
                )
            )
            return self._failed_result(request, errors, now, "Unsafe input detected.")

        extracted_requirements = self._extract_requirements(
            request.implementation_input.original_user_request,
            request.implementation_input.implementation_plan,
        )
        if not extracted_requirements:
            errors.append(
                ErrorDetail(
                    code="NO_TESTABLE_REQUIREMENTS",
                    message="No testable requirements could be extracted from input.",
                    failure_source=FailureSource.MODEL_OUTPUT,
                    workflow_step="test_generation.extract_requirements",
                )
            )
            return self._failed_result(request, errors, now, "Requirement extraction failed.")

        generated_cases, coverage_summary = self._build_test_cases(request, extracted_requirements)

        if not generated_cases:
            errors.append(
                ErrorDetail(
                    code="NO_TEST_CASES_GENERATED",
                    message="No test cases were generated within configured constraints.",
                    failure_source=FailureSource.WORKFLOW,
                    workflow_step="test_generation.build_cases",
                )
            )
            return self._failed_result(request, errors, now, "Test generation produced no cases.")

        metadata = ArtifactMetadata(
            run_id=request.run_id,
            artifact_type=ArtifactType.TEST_CASE_COLLECTION,
            name=f"test-case-collection-{request.run_id}",
            status=ArtifactStatus.DRAFT,
            approval_status=ApprovalStatus.PENDING,
            skill_name="generate-test-cases",
            source_references=request.implementation_input.source_references,
            validation_passed=True,
            created_at=now,
            updated_at=now,
        )

        collection = TestCaseCollection(
            metadata=metadata,
            source_input=request.implementation_input,
            test_cases=generated_cases,
            coverage_summary=dict(coverage_summary),
            uncovered_requirements=[],
            assumptions=request.implementation_input.assumptions,
            warnings=warnings,
            generation_evidence=[],
        )

        output_path = self._collection_output_path(request.run_id)
        persisted = self._artifact_store.create_model(
            metadata=metadata,
            relative_path=output_path,
            model=collection,
        )

        if not persisted.success or persisted.artifact is None:
            errors.extend(persisted.errors)
            if not persisted.errors:
                errors.append(
                    ErrorDetail(
                        code="TEST_COLLECTION_PERSIST_FAILED",
                        message="Artifact store did not persist the generated test collection.",
                        failure_source=FailureSource.TOOL,
                        workflow_step="test_generation.persist",
                    )
                )
            return self._failed_result(request, errors, now, "Test collection persistence failed.")

        prepared_state = self._prepared_state(
            request=request,
            now=now,
            output_artifacts=[persisted.artifact],
            warnings=warnings,
            errors=errors,
        )

        return self._approval_workflow.create_pending_checkpoint(
            workflow_state=prepared_state,
            name="Checkpoint A - Test Case Approval",
            stage=WorkflowStage.AWAITING_TEST_CASE_APPROVAL,
            instructions=(
                "Review the generated test-case collection and either approve it or request "
                "changes before script generation."
            ),
            required_artifacts=[persisted.artifact],
            triggered_by="test-generation-workflow",
        )

    @staticmethod
    def _collection_output_path(run_id: UUID) -> Path:
        return Path(f"specs/generated/{run_id}-test-cases.json")

    @staticmethod
    def _contains_secret_like_input(*values: str) -> bool:
        pattern = re.compile(r"(api[_-]?key|password|secret|token)\s*[:=]", re.IGNORECASE)
        return any(pattern.search(value) for value in values)

    @staticmethod
    def _extract_requirements(
        original_request: str,
        implementation_plan: str | None,
    ) -> list[tuple[str, str]]:
        combined_text = "\n".join([original_request, implementation_plan or ""])
        candidates = re.split(r"[\n\r;]+|(?<=[.!?])\s+", combined_text)

        requirements: list[tuple[str, str]] = []
        seen: set[str] = set()

        for candidate in candidates:
            normalized = candidate.strip(" -\t")
            if len(normalized) < 12:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            requirement_id = f"REQ-{len(requirements) + 1:03d}"
            requirements.append((requirement_id, normalized))

        return requirements

    def _build_test_cases(
        self,
        request: TestCaseGenerationRequest,
        requirements: list[tuple[str, str]],
    ) -> tuple[list[TestCase], defaultdict[str, list[str]]]:
        categories = request.requested_categories
        coverage_summary: defaultdict[str, list[str]] = defaultdict(list)
        generated: list[TestCase] = []
        index = 1

        scenario_kinds: list[str] = []
        if request.include_positive_tests:
            scenario_kinds.append("positive")
        if request.include_negative_tests:
            scenario_kinds.append("negative")
        if request.include_edge_cases:
            scenario_kinds.append("edge")

        for requirement_id, requirement_text in requirements:
            for category in categories:
                for scenario_kind in scenario_kinds:
                    if len(generated) >= request.maximum_test_cases:
                        return generated, coverage_summary

                    test_case_id = f"TC-{category.value.replace('_', '-').upper()}-{index:03d}"
                    index += 1

                    destructive = "delete" in requirement_text.casefold()
                    automation = (
                        AutomationSuitability.NOT_SUITABLE
                        if destructive
                        else AutomationSuitability.SUITABLE
                    )

                    generated_case = TestCase(
                        test_case_id=test_case_id,
                        title=self._title_for_case(category, scenario_kind, requirement_id),
                        description=(
                            f"{scenario_kind.capitalize()} validation for {requirement_id} "
                            f"in {category.value} scope."
                        ),
                        category=category,
                        priority=self._priority_for_category(category, request.default_priority),
                        source_requirement_ids=[requirement_id],
                        source_requirement_text=requirement_text,
                        preconditions=[request.implementation_input.target_scope],
                        test_data=[f"scenario={scenario_kind}"],
                        steps=self._steps_for_scenario(scenario_kind, requirement_text),
                        postconditions=["System remains in a safe and testable state."],
                        automation_suitability=automation,
                        automation_notes=(
                            "Manual control required due to destructive behavior risk."
                            if destructive
                            else None
                        ),
                        required_evidence=["assertion", "screenshot"],
                        safety_considerations=(
                            ["Do not execute destructive behavior without explicit approval."]
                            if destructive
                            else []
                        ),
                        tags=[category.value, scenario_kind],
                        destructive=destructive,
                        requires_live_environment=False,
                        requires_authentication=False,
                        approval_status=ApprovalStatus.PENDING,
                    )

                    generated.append(generated_case)
                    coverage_summary[requirement_id].append(generated_case.test_case_id)

        return generated, coverage_summary

    @staticmethod
    def _title_for_case(category: TestCategory, scenario_kind: str, requirement_id: str) -> str:
        return (
            f"{category.value.replace('_', ' ').title()} {scenario_kind.title()} - {requirement_id}"
        )

    @staticmethod
    def _priority_for_category(
        category: TestCategory,
        default_priority: TestPriority,
    ) -> TestPriority:
        if category is TestCategory.SMOKE:
            return TestPriority.CRITICAL
        if category in {TestCategory.INTEGRATION, TestCategory.FUNCTIONAL_UI}:
            return TestPriority.HIGH
        return default_priority

    @staticmethod
    def _steps_for_scenario(scenario_kind: str, requirement_text: str) -> list[TestStep]:
        return [
            TestStep(
                step_number=1,
                action=f"Prepare scenario input for: {requirement_text}",
                expected_result="Preconditions are satisfied and setup is successful.",
                evidence_required=["setup-log"],
            ),
            TestStep(
                step_number=2,
                action=f"Execute {scenario_kind} flow for the requirement.",
                expected_result="System response matches expected behavior for this scenario.",
                evidence_required=["assertion", "screenshot"],
            ),
        ]

    @staticmethod
    def _prepared_state(
        *,
        request: TestCaseGenerationRequest,
        now: datetime,
        output_artifacts: list[ArtifactReference],
        warnings: list[WarningDetail],
        errors: list[ErrorDetail],
    ) -> WorkflowState:
        transition_a = WorkflowTransition(
            transition_id=uuid4(),
            from_stage=WorkflowStage.INITIALIZED,
            to_stage=WorkflowStage.INPUT_VALIDATED,
            occurred_at=now,
            reason="Validated test generation request.",
            triggered_by="test-generation-workflow",
        )
        transition_b = WorkflowTransition(
            transition_id=uuid4(),
            from_stage=WorkflowStage.INPUT_VALIDATED,
            to_stage=WorkflowStage.TEST_CASES_GENERATED,
            occurred_at=now,
            reason="Generated draft test-case collection.",
            triggered_by="test-generation-workflow",
            artifact_references=output_artifacts,
        )

        return WorkflowState(
            workflow_id=uuid4(),
            current_stage=WorkflowStage.TEST_CASES_GENERATED,
            outcome=WorkflowOutcome.PENDING,
            checkpoints=[],
            transitions=[transition_a, transition_b],
            input_artifacts=[],
            output_artifacts=output_artifacts,
            warnings=warnings,
            errors=errors,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _failed_result(
        request: TestCaseGenerationRequest,
        errors: list[ErrorDetail],
        now: datetime,
        message: str,
    ) -> WorkflowResult:
        failed_state = WorkflowState(
            workflow_id=uuid4(),
            current_stage=WorkflowStage.FAILED,
            outcome=WorkflowOutcome.FAILURE,
            checkpoints=[],
            transitions=[],
            input_artifacts=[],
            output_artifacts=[],
            warnings=[],
            errors=errors,
            created_at=now,
            updated_at=now,
        )

        return WorkflowResult(
            workflow_state=failed_state,
            outcome=WorkflowOutcome.FAILURE,
            message=message,
            produced_artifacts=[],
            warnings=[],
            errors=errors,
        )
