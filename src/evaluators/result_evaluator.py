"""Deterministic evaluator for rubric-based execution result scoring."""

from __future__ import annotations

from dataclasses import dataclass

from src.models.common import ArtifactMetadata, EvidenceReference, WarningDetail, utc_now
from src.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    EvaluationOutcome,
    EvidenceType,
    ExecutionStatus,
    Severity,
)
from src.models.evaluation import (
    CriterionEvaluation,
    EvaluationCriterion,
    EvaluationRequest,
    EvaluationResult,
)


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Prepared evidence and execution aggregates used during scoring."""

    evidence: list[EvidenceReference]
    passed_count: int
    failed_count: int
    timed_out_count: int
    total_count: int

    @property
    def pass_ratio(self) -> float:
        """Return deterministic success ratio from execution outcomes."""

        if self.total_count <= 0:
            return 0.0

        return self.passed_count / self.total_count


class ResultEvaluator:
    """Evaluate deterministic execution outcomes using an approved rubric."""

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        """Create an evaluation result from validated request input."""

        evidence_bundle = self._prepare_evidence_bundle(request)

        criterion_results: list[CriterionEvaluation] = []
        for criterion in request.rubric.criteria:
            criterion_results.append(self._evaluate_criterion(criterion, evidence_bundle))

        weighted_score = self._compute_weighted_score(criterion_results, request.rubric.criteria)
        overall_outcome = self._determine_overall_outcome(criterion_results)

        warnings = self._build_warnings(criterion_results)

        metadata = ArtifactMetadata(
            run_id=request.run_id,
            artifact_type=ArtifactType.EVALUATION_RESULT,
            name=f"evaluation-{request.rubric.rubric_id}-{request.run_id}",
            status=ArtifactStatus.AWAITING_APPROVAL,
            approval_status=ApprovalStatus.PENDING,
            skill_name="evaluation-testing",
            source_references=[request.rubric.rubric_id],
            parent_artifact_ids=[
                result.metadata.artifact_id for result in request.execution_results
            ],
            validation_passed=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        summary = self._build_summary(
            rubric_id=request.rubric.rubric_id,
            criterion_results=criterion_results,
            overall_outcome=overall_outcome,
        )

        return EvaluationResult(
            metadata=metadata,
            rubric_id=request.rubric.rubric_id,
            rubric_version=request.rubric.version,
            criterion_results=criterion_results,
            weighted_score=weighted_score,
            overall_outcome=overall_outcome,
            summary=summary,
            warnings=warnings,
            approval_status=ApprovalStatus.PENDING,
        )

    @staticmethod
    def _prepare_evidence_bundle(request: EvaluationRequest) -> EvidenceBundle:
        evidence: list[EvidenceReference] = []
        passed_count = 0
        failed_count = 0
        timed_out_count = 0

        for execution_result in request.execution_results:
            status = execution_result.status
            if status is ExecutionStatus.PASSED:
                passed_count += 1
            if status is ExecutionStatus.FAILED:
                failed_count += 1
            if status is ExecutionStatus.TIMED_OUT:
                timed_out_count += 1

            evidence.append(
                EvidenceReference(
                    evidence_type=EvidenceType.TEST_RESULT,
                    title=f"Execution result {execution_result.script_artifact_id}",
                    source="playwright",
                    artifact_id=execution_result.metadata.artifact_id,
                    path=execution_result.script_path,
                    metadata={
                        "status": status.value,
                        "passed_tests": execution_result.passed_tests,
                        "failed_tests": execution_result.failed_tests,
                        "timed_out_tests": execution_result.timed_out_tests,
                    },
                )
            )

            evidence.extend(execution_result.evidence)

        evidence.extend(request.additional_evidence)

        total_count = passed_count + failed_count + timed_out_count

        return EvidenceBundle(
            evidence=evidence,
            passed_count=passed_count,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            total_count=total_count,
        )

    def _evaluate_criterion(
        self,
        criterion: EvaluationCriterion,
        evidence_bundle: EvidenceBundle,
    ) -> CriterionEvaluation:
        required_types = {required.casefold() for required in criterion.required_evidence_types}

        supporting_evidence = [
            evidence
            for evidence in evidence_bundle.evidence
            if not required_types or evidence.evidence_type.value.casefold() in required_types
        ]

        if not supporting_evidence:
            return CriterionEvaluation(
                criterion_id=criterion.criterion_id,
                outcome=EvaluationOutcome.INSUFFICIENT_EVIDENCE,
                score=None,
                rationale=(
                    "No evidence matched the criterion required evidence types. "
                    "Provide additional deterministic evidence for scoring."
                ),
                confidence=0.2,
                evidence=[],
                recommendations=[
                    "Capture additional deterministic evidence aligned with this criterion."
                ],
                severity=Severity.MEDIUM,
            )

        scale = criterion.scale
        score = scale.minimum_score + (
            (scale.maximum_score - scale.minimum_score) * evidence_bundle.pass_ratio
        )

        if evidence_bundle.timed_out_count > 0:
            score = max(score - 0.25, scale.minimum_score)

        if score >= scale.passing_score:
            outcome = EvaluationOutcome.PASSED
            severity = Severity.INFORMATIONAL
            recommendations: list[str] = []
        elif score > (scale.minimum_score + scale.passing_score) / 2:
            outcome = EvaluationOutcome.PARTIALLY_PASSED
            severity = Severity.MEDIUM
            recommendations = [
                "Improve failing or unstable execution paths to meet passing threshold."
            ]
        else:
            outcome = EvaluationOutcome.FAILED
            severity = Severity.HIGH
            recommendations = [
                "Address deterministic failures and rerun evaluation for this criterion."
            ]

        confidence = 0.9 if evidence_bundle.total_count > 0 else 0.6

        rationale = (
            f"Criterion scored using deterministic execution evidence. "
            f"Pass ratio: {evidence_bundle.pass_ratio:.2f}; "
            f"computed score: {score:.2f}; "
            f"passing threshold: {scale.passing_score:.2f}."
        )

        return CriterionEvaluation(
            criterion_id=criterion.criterion_id,
            outcome=outcome,
            score=round(score, 4),
            rationale=rationale,
            confidence=confidence,
            evidence=supporting_evidence,
            recommendations=recommendations,
            severity=severity,
        )

    @staticmethod
    def _compute_weighted_score(
        criterion_results: list[CriterionEvaluation],
        criteria: list[EvaluationCriterion],
    ) -> float | None:
        weight_by_id = {criterion.criterion_id: criterion.weight for criterion in criteria}

        scored_entries: list[tuple[float, float]] = []
        for result in criterion_results:
            if result.score is None:
                continue

            weight = weight_by_id.get(result.criterion_id)
            if weight is None:
                continue

            scored_entries.append((result.score, weight))

        if not scored_entries:
            return None

        total_weight = sum(weight for _, weight in scored_entries)
        if total_weight <= 0:
            return None

        weighted_sum = sum(score * weight for score, weight in scored_entries)
        return round(weighted_sum / total_weight, 4)

    @staticmethod
    def _determine_overall_outcome(
        criterion_results: list[CriterionEvaluation],
    ) -> EvaluationOutcome:
        outcomes = {result.outcome for result in criterion_results}

        if EvaluationOutcome.FAILED in outcomes:
            return EvaluationOutcome.FAILED

        if EvaluationOutcome.PARTIALLY_PASSED in outcomes:
            return EvaluationOutcome.PARTIALLY_PASSED

        if EvaluationOutcome.INSUFFICIENT_EVIDENCE in outcomes:
            return EvaluationOutcome.INSUFFICIENT_EVIDENCE

        if outcomes == {EvaluationOutcome.NOT_APPLICABLE}:
            return EvaluationOutcome.NOT_APPLICABLE

        if outcomes == {EvaluationOutcome.NOT_EVALUATED}:
            return EvaluationOutcome.NOT_EVALUATED

        return EvaluationOutcome.PASSED

    @staticmethod
    def _build_warnings(criterion_results: list[CriterionEvaluation]) -> list[WarningDetail]:
        warnings: list[WarningDetail] = []

        for result in criterion_results:
            if result.outcome is EvaluationOutcome.INSUFFICIENT_EVIDENCE:
                warnings.append(
                    WarningDetail(
                        code="EVALUATION_INSUFFICIENT_EVIDENCE",
                        message=(
                            f"Criterion {result.criterion_id} has insufficient evidence "
                            "for deterministic scoring."
                        ),
                        severity=Severity.MEDIUM,
                        source="result-evaluator",
                        suggested_action=(
                            "Collect additional deterministic evidence and re-evaluate."
                        ),
                    )
                )

            if result.confidence < 0.7:
                warnings.append(
                    WarningDetail(
                        code="EVALUATION_LOW_CONFIDENCE",
                        message=f"Criterion {result.criterion_id} has low confidence.",
                        severity=Severity.LOW,
                        source="result-evaluator",
                        suggested_action="Increase evidence coverage for this criterion.",
                    )
                )

        return warnings

    @staticmethod
    def _build_summary(
        rubric_id: str,
        criterion_results: list[CriterionEvaluation],
        overall_outcome: EvaluationOutcome,
    ) -> str:
        total = len(criterion_results)
        passed = sum(
            1 for result in criterion_results if result.outcome is EvaluationOutcome.PASSED
        )
        partially = sum(
            1
            for result in criterion_results
            if result.outcome is EvaluationOutcome.PARTIALLY_PASSED
        )
        failed = sum(
            1 for result in criterion_results if result.outcome is EvaluationOutcome.FAILED
        )
        insufficient = sum(
            1
            for result in criterion_results
            if result.outcome is EvaluationOutcome.INSUFFICIENT_EVIDENCE
        )

        return (
            f"Rubric {rubric_id} evaluated across {total} criteria. "
            f"Passed: {passed}, partially passed: {partially}, "
            f"failed: {failed}, insufficient evidence: {insufficient}. "
            f"Overall outcome: {overall_outcome.value}."
        )
