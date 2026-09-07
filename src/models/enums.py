"""Shared enumerations for the Testing and Evaluation Agent."""

from __future__ import annotations

from enum import StrEnum


class TestCategory(StrEnum):
    """Supported categories for generated and approved test cases."""

    SMOKE = "smoke"
    INTEGRATION = "integration"
    SELF_TEST = "self_test"
    FUNCTIONAL_UI = "functional_ui"
    VISUAL_UI = "visual_ui"
    RESPONSIVE_UI = "responsive_ui"
    PERFORMANCE = "performance"
    USABILITY = "usability"
    ACCESSIBILITY = "accessibility"
    AI_EVALUATION = "ai_evaluation"
    PLAN_VS_IMPLEMENTATION = "plan_vs_implementation"


class TestPriority(StrEnum):
    """Priority assigned to a test case."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AutomationSuitability(StrEnum):
    """Suitability of a test case for deterministic automation."""

    SUITABLE = "suitable"
    PARTIALLY_SUITABLE = "partially_suitable"
    NOT_SUITABLE = "not_suitable"
    REQUIRES_EXPLORATION = "requires_exploration"


class ApprovalStatus(StrEnum):
    """Human approval state of a controlled artifact."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ArtifactType(StrEnum):
    """Types of artifacts managed by the agent."""

    IMPLEMENTATION_PLAN = "implementation_plan"
    TEST_CASE_COLLECTION = "test_case_collection"
    TEST_CASE = "test_case"
    PLAYWRIGHT_SCRIPT = "playwright_script"
    EXECUTION_RESULT = "execution_result"
    EVALUATION_RESULT = "evaluation_result"
    PLAN_COMPARISON = "plan_comparison"
    REPORT = "report"
    SCREENSHOT = "screenshot"
    TRACE = "trace"
    VIDEO = "video"
    TEST_TARGET = "test_target"
    TEST_RUN = "test_run"
    CONVERSATION_SESSION = "conversation_session"
    REUSABLE_ASSET = "reusable_asset"
    RUBRIC = "rubric"
    BASELINE = "baseline"
    FIXTURE = "fixture"
    ENVIRONMENT_PROFILE = "environment_profile"
    LOCATOR_KNOWLEDGE = "locator_knowledge"


class ArtifactStatus(StrEnum):
    """Lifecycle state of an artifact."""

    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXECUTED = "executed"
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    REUSED = "reused"


class WorkflowStage(StrEnum):
    """Ordered stages of the initial end-to-end workflow."""

    INITIALIZED = "initialized"
    INPUT_VALIDATED = "input_validated"
    TEST_CASES_GENERATED = "test_cases_generated"
    AWAITING_TEST_CASE_APPROVAL = "awaiting_test_case_approval"
    TEST_CASES_APPROVED = "test_cases_approved"
    PLAYWRIGHT_SCRIPTS_GENERATED = "playwright_scripts_generated"
    AWAITING_SCRIPT_APPROVAL = "awaiting_script_approval"
    PLAYWRIGHT_SCRIPTS_APPROVED = "playwright_scripts_approved"
    READY_FOR_EXECUTION = "ready_for_execution"
    EXECUTION_IN_PROGRESS = "execution_in_progress"
    EXECUTION_COMPLETED = "execution_completed"
    EVALUATION_COMPLETED = "evaluation_completed"
    AWAITING_EVALUATION_APPROVAL = "awaiting_evaluation_approval"
    EVALUATION_APPROVED = "evaluation_approved"
    PLAN_COMPARISON_COMPLETED = "plan_comparison_completed"
    REPORT_GENERATED = "report_generated"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowOutcome(StrEnum):
    """Final or intermediate outcome of a workflow operation."""

    PENDING = "pending"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ExecutionStatus(StrEnum):
    """Execution state of a deterministic test run."""

    NOT_STARTED = "not_started"
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class BrowserName(StrEnum):
    """Browsers supported by the Playwright execution layer."""

    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class EvidenceType(StrEnum):
    """Evidence types that may support testing and evaluation findings."""

    TEST_RESULT = "test_result"
    ASSERTION = "assertion"
    SCREENSHOT = "screenshot"
    TRACE = "trace"
    VIDEO = "video"
    ACCESSIBILITY_SNAPSHOT = "accessibility_snapshot"
    CONSOLE_LOG = "console_log"
    NETWORK_LOG = "network_log"
    SOURCE_FILE = "source_file"
    REPORT = "report"
    USER_INPUT = "user_input"
    IMPLEMENTATION_PLAN = "implementation_plan"
    MODEL_OUTPUT = "model_output"
    MCP_OBSERVATION = "mcp_observation"


class FailureSource(StrEnum):
    """Likely source of an observed failure."""

    APPLICATION = "application"
    TEST_SCRIPT = "test_script"
    TEST_DATA = "test_data"
    ENVIRONMENT = "environment"
    CONFIGURATION = "configuration"
    AGENT = "agent"
    WORKFLOW = "workflow"
    SKILL = "skill"
    TOOL = "tool"
    MODEL_OUTPUT = "model_output"
    MCP_CONNECTION = "mcp_connection"
    AUTHENTICATION = "authentication"
    APPROVAL = "approval"
    UNKNOWN = "unknown"


class EvaluationOutcome(StrEnum):
    """Normalized result of evaluating one criterion."""

    PASSED = "passed"
    PARTIALLY_PASSED = "partially_passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    NOT_EVALUATED = "not_evaluated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RequirementStatus(StrEnum):
    """Implementation status of a requirement during independent review."""

    FULLY_IMPLEMENTED = "fully_implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    MISSING = "missing"
    CHANGED = "changed"
    ADDITIONAL_UNREQUESTED_BEHAVIOR = "additional_unrequested_behavior"
    NOT_VERIFIABLE = "not_verifiable"


class Severity(StrEnum):
    """Severity assigned to a finding, failure, or recommendation."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class ReportFormat(StrEnum):
    """Supported final report formats."""

    JSON = "json"
    MARKDOWN = "markdown"
    BOTH = "both"


class TargetType(StrEnum):
    """Classification of a registered test target."""

    WEB_APP = "web_app"
    POWER_APP = "power_app"
    CODE_APP = "code_app"
    VSCODE_EXTENSION = "vscode_extension"
    GENERIC_REPO = "generic_repo"
    PLUGIN_GENERATED_CODE_APP = "plugin_generated_code_app"


class ConversationState(StrEnum):
    """Progressive states of an interactive testing conversation."""

    AWAITING_TARGET_TYPE = "awaiting_target_type"
    AWAITING_TARGET_IDENTITY = "awaiting_target_identity"
    AWAITING_TARGET_SOURCE = "awaiting_target_source"
    AWAITING_ENVIRONMENT = "awaiting_environment"
    AWAITING_SCOPE = "awaiting_scope"
    AWAITING_RESTRICTIONS = "awaiting_restrictions"
    CHECKING_PREVIOUS_RUNS = "checking_previous_runs"
    OFFERING_REUSABLE_ASSETS = "offering_reusable_assets"
    AWAITING_SCOPE_CONFIRMATION = "awaiting_scope_confirmation"
    GENERATING_TEST_CASES = "generating_test_cases"
    AWAITING_TEST_CASE_APPROVAL = "awaiting_test_case_approval"
    GENERATING_SCRIPTS = "generating_scripts"
    AWAITING_SCRIPT_APPROVAL = "awaiting_script_approval"
    AWAITING_EXECUTION_TRIGGER = "awaiting_execution_trigger"
    EXECUTING = "executing"
    EVALUATING = "evaluating"
    AWAITING_EVALUATION_APPROVAL = "awaiting_evaluation_approval"
    COMPARING = "comparing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReusableAssetKind(StrEnum):
    """Kinds of approved artifacts eligible for cross-run reuse."""

    TEST_CASE = "test_case"
    PLAYWRIGHT_SCRIPT = "playwright_script"
    RUBRIC = "rubric"
    BASELINE = "baseline"
    FIXTURE = "fixture"
    ENVIRONMENT_PROFILE = "environment_profile"
    LOCATOR_KNOWLEDGE = "locator_knowledge"
