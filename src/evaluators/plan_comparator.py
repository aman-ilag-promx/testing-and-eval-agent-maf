"""Deterministic comparator for plan-versus-implementation analysis."""

from __future__ import annotations

from uuid import UUID, uuid4

from src.models.common import ArtifactMetadata, EvidenceReference, utc_now
from src.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    EvaluationOutcome,
    EvidenceType,
    ExecutionStatus,
    RequirementStatus,
    Severity,
)
from src.models.evaluation import EvaluationResult
from src.models.plan_comparison import (
    PlanComparisonFinding,
    PlanComparisonRequest,
    PlanComparisonResult,
    RequirementEvidence,
    SourceRequirement,
    SuggestedImprovement,
)
from src.models.playwright import PlaywrightExecutionResult


class PlanComparator:
    """Classify requirement implementation state using deterministic evidence."""

    def compare(self, request: PlanComparisonRequest) -> PlanComparisonResult:
        """Produce a structured plan-comparison result from validated input."""

        findings: list[PlanComparisonFinding] = []
        all_improvements: list[SuggestedImprovement] = []

        unmatched_artifact_ids = {
            artifact.artifact_id for artifact in request.implementation_artifacts
        }

        for requirement in request.requirements:
            matched_artifacts = self._find_matching_artifacts(request, requirement)
            for artifact in matched_artifacts:
                unmatched_artifact_ids.discard(artifact.artifact_id)

            finding, improvements = self._build_requirement_finding(
                requirement=requirement,
                matched_artifacts=matched_artifacts,
                execution_results=request.execution_results,
                evaluation_results=request.evaluation_results,
            )
            findings.append(finding)
            all_improvements.extend(improvements)

        findings.extend(
            self._build_additional_behavior_findings(
                request=request,
                unmatched_artifact_ids=unmatched_artifact_ids,
            )
        )

        metadata = ArtifactMetadata(
            run_id=self._derive_run_id(request),
            artifact_type=ArtifactType.PLAN_COMPARISON,
            name="plan-comparison-result",
            status=ArtifactStatus.AWAITING_APPROVAL,
            approval_status=ApprovalStatus.PENDING,
            skill_name="plan-vs-implementation",
            source_references=request.original_input.source_references,
            parent_artifact_ids=[
                artifact.artifact_id for artifact in request.implementation_artifacts
            ],
            validation_passed=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        limitations = self._build_limitations(request, findings)

        summary = self._build_summary(request.requirements, findings)

        return PlanComparisonResult(
            artifact_metadata=metadata,
            requirements=request.requirements,
            findings=findings,
            suggested_improvements=self._deduplicate_improvements(all_improvements),
            summary=summary,
            limitations=limitations,
            requires_human_review=True,
        )

    @staticmethod
    def _find_matching_artifacts(
        request: PlanComparisonRequest,
        requirement: SourceRequirement,
    ) -> list[ArtifactMetadata]:
        requirement_terms = {
            requirement.requirement_id.casefold(),
            requirement.title.casefold(),
        }
        requirement_terms.update(
            reference.casefold() for reference in requirement.source_references
        )

        matched: list[ArtifactMetadata] = []
        for artifact in request.implementation_artifacts:
            candidate_terms = {
                artifact.name.casefold(),
                *(reference.casefold() for reference in artifact.source_references),
            }
            if requirement_terms.intersection(candidate_terms):
                matched.append(artifact)

        return matched

    def _build_requirement_finding(
        self,
        *,
        requirement: SourceRequirement,
        matched_artifacts: list[ArtifactMetadata],
        execution_results: list[PlaywrightExecutionResult],
        evaluation_results: list[EvaluationResult],
    ) -> tuple[PlanComparisonFinding, list[SuggestedImprovement]]:
        pass_count = sum(
            1 for result in execution_results if result.status is ExecutionStatus.PASSED
        )
        fail_count = sum(
            1
            for result in execution_results
            if result.status in {ExecutionStatus.FAILED, ExecutionStatus.TIMED_OUT}
        )

        evaluation_failed = any(
            result.overall_outcome in {EvaluationOutcome.FAILED, EvaluationOutcome.PARTIALLY_PASSED}
            for result in evaluation_results
        )

        evidence: list[RequirementEvidence] = []

        for artifact in matched_artifacts:
            evidence_reference = EvidenceReference(
                evidence_type=EvidenceType.SOURCE_FILE,
                title=f"Artifact {artifact.name}",
                source="implementation-artifact",
                artifact_id=artifact.artifact_id,
                metadata={
                    "artifact_type": artifact.artifact_type.value,
                    "artifact_status": artifact.status.value,
                },
            )
            evidence.append(
                RequirementEvidence(
                    requirement_id=requirement.requirement_id,
                    evidence=evidence_reference,
                    supports_claim=True,
                    is_conclusive=False,
                    explanation="Implementation artifact references this requirement.",
                )
            )

        for execution_result in execution_results:
            evidence.append(
                RequirementEvidence(
                    requirement_id=requirement.requirement_id,
                    evidence=EvidenceReference(
                        evidence_type=EvidenceType.TEST_RESULT,
                        title=f"Execution {execution_result.script_artifact_id}",
                        source="playwright",
                        artifact_id=execution_result.metadata.artifact_id,
                        path=execution_result.script_path,
                        metadata={
                            "status": execution_result.status.value,
                        },
                    ),
                    supports_claim=execution_result.status is ExecutionStatus.PASSED,
                    is_conclusive=False,
                    explanation="Execution result contributes to implementation confidence.",
                )
            )

        status: RequirementStatus
        severity: Severity
        gap_impact: str | None
        improvements: list[SuggestedImprovement] = []

        if not matched_artifacts and requirement.is_mandatory:
            status = RequirementStatus.MISSING
            severity = Severity.HIGH
            gap_impact = "No implementation artifact was mapped to this mandatory requirement."
            improvements.append(
                SuggestedImprovement(
                    description="Implement the missing requirement behavior and link artifacts.",
                    rationale="Mandatory requirement has no mapped implementation artifact.",
                    priority=Severity.HIGH,
                    affected_requirement_ids=[requirement.requirement_id],
                )
            )
            if not evidence:
                evidence.append(
                    RequirementEvidence(
                        requirement_id=requirement.requirement_id,
                        evidence=EvidenceReference(
                            evidence_type=EvidenceType.REPORT,
                            title="Missing implementation evidence",
                            source="plan-comparator",
                            metadata={"reason": "No artifact mapping found"},
                        ),
                        supports_claim=False,
                        is_conclusive=False,
                        explanation="No implementation artifact matched this requirement.",
                    )
                )
        elif matched_artifacts and fail_count == 0 and pass_count > 0 and not evaluation_failed:
            status = RequirementStatus.FULLY_IMPLEMENTED
            severity = Severity.INFORMATIONAL
            gap_impact = None
        elif matched_artifacts and (fail_count > 0 or evaluation_failed):
            status = RequirementStatus.PARTIALLY_IMPLEMENTED
            severity = Severity.MEDIUM
            gap_impact = (
                "Implementation exists, but deterministic evidence includes "
                "failures or quality gaps."
            )
            improvements.append(
                SuggestedImprovement(
                    description="Address failing or unstable behavior for this requirement.",
                    rationale=(
                        "Execution or evaluation evidence indicates incomplete "
                        "implementation quality."
                    ),
                    priority=Severity.MEDIUM,
                    affected_requirement_ids=[requirement.requirement_id],
                )
            )
        elif matched_artifacts and pass_count == 0 and fail_count == 0:
            status = RequirementStatus.NOT_VERIFIABLE
            severity = Severity.LOW
            gap_impact = "No deterministic execution evidence was available for verification."
            evidence = []
        else:
            status = RequirementStatus.CHANGED
            severity = Severity.MEDIUM
            gap_impact = "Implementation behavior may diverge from the expected requirement intent."
            improvements.append(
                SuggestedImprovement(
                    description="Review implementation alignment with original requirement intent.",
                    rationale=(
                        "Artifact mapping exists, but evidence does not confirm expected behavior."
                    ),
                    priority=Severity.MEDIUM,
                    affected_requirement_ids=[requirement.requirement_id],
                )
            )

        finding = PlanComparisonFinding(
            finding_id=uuid4(),
            requirement_id=requirement.requirement_id,
            status=status,
            summary=self._summary_for_status(requirement.requirement_id, status),
            evidence=evidence,
            gap_impact=gap_impact,
            severity=severity,
            suggested_improvements=improvements,
        )

        return finding, improvements

    @staticmethod
    def _build_additional_behavior_findings(
        request: PlanComparisonRequest,
        unmatched_artifact_ids: set[UUID],
    ) -> list[PlanComparisonFinding]:
        findings: list[PlanComparisonFinding] = []
        artifact_by_id = {
            artifact.artifact_id: artifact for artifact in request.implementation_artifacts
        }

        for index, artifact_id in enumerate(sorted(unmatched_artifact_ids, key=str), start=1):
            artifact = artifact_by_id[artifact_id]
            findings.append(
                PlanComparisonFinding(
                    finding_id=uuid4(),
                    requirement_id=f"UNREQUESTED-{index:03d}",
                    status=RequirementStatus.ADDITIONAL_UNREQUESTED_BEHAVIOR,
                    summary=(
                        f"Artifact {artifact.name} is not mapped to an extracted requirement."
                    ),
                    evidence=[
                        RequirementEvidence(
                            requirement_id=f"UNREQUESTED-{index:03d}",
                            evidence=EvidenceReference(
                                evidence_type=EvidenceType.SOURCE_FILE,
                                title=f"Unmapped artifact {artifact.name}",
                                source="implementation-artifact",
                                artifact_id=artifact.artifact_id,
                                metadata={
                                    "artifact_type": artifact.artifact_type.value,
                                    "artifact_status": artifact.status.value,
                                },
                            ),
                            supports_claim=False,
                            is_conclusive=False,
                            explanation="Artifact has no matching requirement mapping.",
                        )
                    ],
                    gap_impact="Potential scope expansion or undocumented behavior.",
                    severity=Severity.LOW,
                    suggested_improvements=[
                        SuggestedImprovement(
                            description=(
                                "Review and document whether this additional behavior is intended."
                            ),
                            rationale="Unmapped artifact may represent scope drift.",
                            priority=Severity.LOW,
                            affected_requirement_ids=[],
                        )
                    ],
                )
            )

        return findings

    @staticmethod
    def _summary_for_status(requirement_id: str, status: RequirementStatus) -> str:
        return f"Requirement {requirement_id} classified as {status.value}."

    @staticmethod
    def _build_limitations(
        request: PlanComparisonRequest,
        findings: list[PlanComparisonFinding],
    ) -> list[str]:
        limitations: list[str] = []

        if not request.execution_results:
            limitations.append("No execution results were provided for deterministic verification.")

        if not request.evaluation_results:
            limitations.append(
                "No evaluation results were provided for quality comparison context."
            )

        if any(finding.status is RequirementStatus.NOT_VERIFIABLE for finding in findings):
            limitations.append("At least one requirement is not verifiable with current evidence.")

        return limitations

    @staticmethod
    def _build_summary(
        requirements: list[SourceRequirement],
        findings: list[PlanComparisonFinding],
    ) -> str:
        total_requirements = len(requirements)
        status_counts: dict[RequirementStatus, int] = {}
        for finding in findings:
            status_counts[finding.status] = status_counts.get(finding.status, 0) + 1

        fully_implemented = status_counts.get(RequirementStatus.FULLY_IMPLEMENTED, 0)
        partially_implemented = status_counts.get(RequirementStatus.PARTIALLY_IMPLEMENTED, 0)
        missing = status_counts.get(RequirementStatus.MISSING, 0)
        changed = status_counts.get(RequirementStatus.CHANGED, 0)
        additional = status_counts.get(RequirementStatus.ADDITIONAL_UNREQUESTED_BEHAVIOR, 0)
        not_verifiable = status_counts.get(RequirementStatus.NOT_VERIFIABLE, 0)

        return (
            f"Compared {total_requirements} requirements. "
            f"Fully implemented: {fully_implemented}, "
            f"partially implemented: {partially_implemented}, "
            f"missing: {missing}, changed: {changed}, additional behavior: {additional}, "
            f"not verifiable: {not_verifiable}."
        )

    @staticmethod
    def _derive_run_id(request: PlanComparisonRequest) -> UUID:
        if request.implementation_artifacts:
            return request.implementation_artifacts[0].run_id

        if request.execution_results:
            return request.execution_results[0].metadata.run_id

        if request.evaluation_results:
            return request.evaluation_results[0].metadata.run_id

        return uuid4()

    @staticmethod
    def _deduplicate_improvements(
        improvements: list[SuggestedImprovement],
    ) -> list[SuggestedImprovement]:
        deduplicated: list[SuggestedImprovement] = []
        seen_keys: set[tuple[str, str]] = set()

        for improvement in improvements:
            key = (improvement.description.casefold(), improvement.rationale.casefold())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduplicated.append(improvement)

        return deduplicated
