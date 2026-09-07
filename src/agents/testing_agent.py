"""Top-level orchestration class for testing and evaluation workflows."""

from __future__ import annotations

from uuid import UUID

from src.agents.conversation_agent import ConversationAgent
from src.agents.instructions import build_agent_instructions
from src.agents.model_client import ModelClient, ModelRequest, create_model_client
from src.config import Settings, get_settings
from src.models.common import ArtifactReference, OperationResult
from src.models.conversation import ConversationSession
from src.models.enums import ApprovalStatus, WorkflowStage
from src.models.evaluation import EvaluationRequest
from src.models.playwright import PlaywrightScriptGenerationRequest
from src.models.test_cases import TestCaseGenerationRequest
from src.models.workflow import WorkflowResult, WorkflowState
from src.tools.playwright_mcp_adapter import PlaywrightMCPAdapter
from src.workflows.approval_workflow import ApprovalWorkflow
from src.workflows.evaluation_workflow import EvaluationWorkflow
from src.workflows.repository_workflow import RepositoryWorkflow
from src.workflows.script_generation_workflow import ScriptGenerationWorkflow
from src.workflows.test_generation_workflow import TestGenerationWorkflow


class TestingEvaluationAgent:
    """Approval-aware orchestrator that delegates to deterministic workflows."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        model_client: ModelClient | None = None,
        approval_workflow: ApprovalWorkflow | None = None,
        test_generation_workflow: TestGenerationWorkflow | None = None,
        script_generation_workflow: ScriptGenerationWorkflow | None = None,
        evaluation_workflow: EvaluationWorkflow | None = None,
        repository_workflow: RepositoryWorkflow | None = None,
        playwright_mcp_adapter: PlaywrightMCPAdapter | None = None,
    ) -> None:
        """Initialize deterministic dependencies and workflow adapters."""

        self._settings = settings or get_settings()
        self._settings.ensure_output_directories()

        self._model_client = model_client or create_model_client(settings=self._settings)

        self._approval_workflow = approval_workflow or ApprovalWorkflow()
        self._test_generation_workflow = test_generation_workflow or TestGenerationWorkflow(
            approval_workflow=self._approval_workflow
        )
        self._script_generation_workflow = script_generation_workflow or ScriptGenerationWorkflow(
            approval_workflow=self._approval_workflow
        )
        self._evaluation_workflow = evaluation_workflow or EvaluationWorkflow(
            approval_workflow=self._approval_workflow
        )
        self._repository_workflow = repository_workflow or RepositoryWorkflow()
        self._playwright_mcp_adapter = playwright_mcp_adapter or PlaywrightMCPAdapter(
            settings=self._settings
        )
        self._conversation_agent = ConversationAgent(model_client=self._model_client)

    @property
    def settings(self) -> Settings:
        """Return resolved runtime settings."""

        return self._settings

    def summarize_intent(self, user_prompt: str) -> str:
        """Use the model client to generate a concise run-intent summary."""

        response = self._model_client.invoke(
            ModelRequest(
                user_prompt=user_prompt,
                system_prompt=(
                    f"{build_agent_instructions(self._settings)}\n"
                    "Summarize only the user's testing intent in two concise sentences. "
                    "Do not claim execution, approval, generated artifacts, identifiers, "
                    "or information not present in the request."
                ),
                temperature=self._settings.AGENT_TEMPERATURE,
                max_output_tokens=8_000,
            )
        )
        return response.content

    def generate_test_cases(self, request: TestCaseGenerationRequest) -> WorkflowResult:
        """Run checkpoint-A test-case generation workflow."""

        return self._test_generation_workflow.run(request)

    def generate_playwright_scripts(
        self,
        request: PlaywrightScriptGenerationRequest,
    ) -> WorkflowResult:
        """Run checkpoint-B script generation workflow."""

        return self._script_generation_workflow.run(request)

    def evaluate_results(self, request: EvaluationRequest) -> WorkflowResult:
        """Run checkpoint-C evaluation workflow."""

        return self._evaluation_workflow.run(request)

    def collect_github_evidence(
        self,
        repository_url: str,
        *,
        code_query: str | None = None,
    ) -> OperationResult:
        """Collect read-only GitHub MCP observations for test design and evaluation."""
        return self._repository_workflow.collect_github_evidence(
            repository_url,
            code_query=code_query,
        )

    def collect_playwright_snapshot(self, target_url: str) -> OperationResult:
        """Collect an optional browser observation without executing a test script."""

        return self._playwright_mcp_adapter.take_snapshot(target_url)

    def apply_approval_decision(
        self,
        *,
        workflow_state: WorkflowState,
        checkpoint_id: UUID,
        artifact_reference: ArtifactReference,
        decision: ApprovalStatus,
        reviewer: str,
        comments: str | None,
        next_stage_on_approval: WorkflowStage,
        revision_stage_on_rejection: WorkflowStage,
    ) -> WorkflowResult:
        """Apply explicit human approval/rejection for a workflow checkpoint."""

        return self._approval_workflow.record_decision(
            workflow_state=workflow_state,
            checkpoint_id=checkpoint_id,
            artifact_reference=artifact_reference,
            status=decision,
            reviewer=reviewer,
            comments=comments,
            next_stage_on_approval=next_stage_on_approval,
            revision_stage_on_rejection=revision_stage_on_rejection,
            triggered_by="testing-evaluation-agent",
        )

    def start_conversation(self, target_type_hint: str | None = None) -> ConversationSession:
        """Start a new interactive testing session."""
        return self._conversation_agent.start_session(target_type_hint=target_type_hint)

    def resume_conversation(self, session_id: UUID) -> ConversationSession:
        """Resume an existing interactive testing session."""
        return self._conversation_agent.resume_session(session_id)

    def health_snapshot(self) -> dict[str, object]:
        """Return safe runtime status for diagnostics."""
        return {
            "environment": self._settings.APP_ENV,
            "foundry_configured": self._settings.foundry_configured,
            "maf_auth_mode": self._settings.MAF_AUTH_MODE,
            "approval_gates_enabled": self._settings.approval_gates_enabled,
            "allow_live_execution": self._settings.ALLOW_LIVE_TEST_EXECUTION,
            "allow_destructive_tests": self._settings.ALLOW_DESTRUCTIVE_TESTS,
        }


def create_testing_agent(settings: Settings | None = None) -> TestingEvaluationAgent:
    """Factory helper for creating a configured testing agent."""

    return TestingEvaluationAgent(settings=settings)
