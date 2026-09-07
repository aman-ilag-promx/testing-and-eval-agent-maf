"""Unit tests for shared model validation behavior."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.models.common import ApprovalRecord, ErrorDetail, OperationResult
from src.models.enums import ApprovalStatus, FailureSource


def test_approval_record_accepts_inline_completed_decision() -> None:
    """Completed approvals can be created with a single decision timestamp."""

    decided_at = datetime.now(UTC)

    record = ApprovalRecord(
        artifact_id=uuid4(),
        status=ApprovalStatus.APPROVED,
        reviewer="Aman Ilag",
        comments="Approved for script generation.",
        decided_at=decided_at,
    )

    assert record.status is ApprovalStatus.APPROVED
    assert record.reviewer == "Aman Ilag"
    assert record.requested_at == decided_at
    assert record.decided_at == decided_at


def test_operation_result_rejects_success_with_blocking_errors() -> None:
    """Successful operation results must not contain blocking errors."""

    error = ErrorDetail(
        code="TEST_ERROR",
        message="Blocking test error",
        failure_source=FailureSource.TOOL,
    )

    with pytest.raises(ValidationError):
        OperationResult(success=True, message="Invalid success", errors=[error])
