"""LLM-driven conversational workflow for interactive testing sessions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.models.common import utc_now
from src.models.conversation import ConversationSession
from src.models.enums import ConversationState, TargetType, TestCategory
from src.tools.run_manifest import RunManifestStore
from src.tools.session_store import SessionStore
from src.tools.target_registry import TargetRegistry

if TYPE_CHECKING:
    from src.agents.model_client import ModelClient


# Instructs the model to extract structured fields and ask natural follow-ups
_SYSTEM_PROMPT = """\
You are a friendly testing assistant that helps users configure automated testing sessions.

Collect these fields through natural conversation:
- target_type  : one of web_app | power_app | code_app | vscode_extension | generic_repo
- target_name  : short descriptive name (e.g. "customer-portal")
- target_url   : URL or local path (optional for non-web targets)
- environment  : one of development | test | staging  — PRODUCTION IS BLOCKED, never accept it
- test_scope   : one or more of: smoke, integration, functional_ui, visual_ui, responsive_ui,
                 performance, usability, accessibility, ai_evaluation
- restrictions : operations to avoid (optional, can be empty)

Rules:
1. Ask ONLY for fields that are still missing — never re-ask for what is already collected.
2. If the user says "production", explain it is blocked and ask for staging, test, or development.
3. Be conversational and concise — not robotic or list-heavy.
4. When target_type, target_name, environment, and test_scope are all known, present a brief
   confirmation summary and set all_collected to true.
5. Update a field when the user explicitly asks to change it.

Respond with ONLY a valid JSON object (no markdown fences, no extra text outside the JSON):
{
  "reply": "Your natural reply to the user",
  "extracted": {
    "target_type": null or one valid value,
    "target_name": null or string,
    "target_url": null or string,
    "environment": null or one valid value,
    "test_scope": null or array of valid values,
    "restrictions": array of strings
  },
  "all_collected": true if target_type + target_name + environment + test_scope are all known,
  "summary": null or short confirmation summary when all_collected is true
}"""


class ConversationWorkflowError(ValueError):
    """Base error raised by the conversation workflow."""


class ConversationWorkflow:
    """LLM-driven conversation that collects testing session data through natural dialogue.

    Business logic only — no terminal input or output.
    The CLI layer reads and renders session.pending_question.
    """

    def __init__(
        self,
        model_client: ModelClient | None = None,
        session_store: SessionStore | None = None,
        target_registry: TargetRegistry | None = None,
        run_manifest_store: RunManifestStore | None = None,
    ) -> None:
        if model_client is None:
            from src.agents.model_client import create_model_client
            model_client = create_model_client()
        self._model_client = model_client
        self._session_store = session_store or SessionStore()
        self._target_registry = target_registry or TargetRegistry()
        self._run_manifest_store = run_manifest_store or RunManifestStore()

    def start(self) -> ConversationSession:
        """Create and persist a new session with an initial greeting."""
        session = ConversationSession()
        greeting = (
            "Hello! I'm your testing assistant. Tell me what you'd like to test.\n\n"
            "You can describe it naturally, for example:\n"
            "  \"I want to smoke test my web app at https://myapp.com in staging\"\n"
            "  \"Run UI tests on a VS Code extension in development\"\n\n"
            "I'll ask follow-up questions for anything I still need."
        )
        session.add_message("agent", greeting)
        object.__setattr__(session, "pending_question", greeting)
        self._session_store.save(session)
        return session

    def resume(self, session_id: UUID) -> ConversationSession:
        """Load an existing session and re-present its pending question."""
        session = self._session_store.load(session_id)
        if session.is_terminal():
            raise ConversationWorkflowError(
                f"Session {session_id} is in terminal state ({session.state}) "
                "and cannot be resumed."
            )
        object.__setattr__(session, "resumed_at", utc_now())
        return session

    def advance(self, session: ConversationSession, user_input: str) -> ConversationSession:
        """Process user input, update session state via Foundry model, and persist."""
        if session.is_terminal():
            raise ConversationWorkflowError(
                f"Session {session.session_id} is terminal and cannot be advanced."
            )

        stripped = user_input.strip()
        session.add_message("user", stripped or "(empty)")

        # Confirmation is deterministic: interpret user intent, fall back to LLM for ambiguous input
        if session.state == ConversationState.AWAITING_SCOPE_CONFIRMATION:
            lower = stripped.lower()
            # "no changes" = proceed; lone "no" = wants to modify
            is_no_changes = "no change" in lower or "no modification" in lower
            first_word = lower.split()[0] if stripped else ""
            _CONFIRM_WORDS = {
                "yes", "y", "confirm", "ok", "okay", "proceed", "go", "start", "sure",
                "yep", "yup", "do", "run", "execute", "begin", "continue", "fine",
                "correct", "right", "good", "great", "perfect", "absolutely",
            }
            if first_word in _CONFIRM_WORDS or is_no_changes:
                object.__setattr__(session, "scope_confirmed", True)
                new_session = _set_state(session, ConversationState.GENERATING_TEST_CASES)
                object.__setattr__(new_session, "updated_at", utc_now())
                self._session_store.save(new_session)
                return new_session
            # Anything else — let LLM interpret the change request
            object.__setattr__(session, "state", ConversationState.AWAITING_TARGET_TYPE)

        new_session = self._llm_turn(session)
        object.__setattr__(new_session, "updated_at", utc_now())
        self._session_store.save(new_session)
        return new_session

    # ------------------------------------------------------------------
    # LLM turn
    # ------------------------------------------------------------------

    def _llm_turn(self, session: ConversationSession) -> ConversationSession:
        """Send conversation history to Foundry and merge the extracted fields."""
        from src.agents.model_client import ModelInvocationError
        # Map "agent" → "assistant" for OpenAI-compatible API
        role_map = {"agent": "assistant", "user": "user", "system": "system"}
        messages = [
            {"role": role_map.get(message.role, message.role), "content": message.content}
            for message in session.messages
        ]
        system_prompt = _SYSTEM_PROMPT + _collected_context(session)

        try:
            response = self._model_client.invoke_chat(messages, system_prompt=system_prompt)
            data = _parse_json_response(response.content)
        except (ModelInvocationError, ValueError) as exc:
            reply = (
                "I had trouble processing that — could you rephrase or add more detail?\n"
                "For example: \"Smoke test my web app at https://example.com in staging.\""
            )
            session.add_message("agent", reply)
            object.__setattr__(session, "pending_question", reply)
            session.warnings.append(f"LLM turn error: {exc}")
            return session

        _merge_extracted(session, data.get("extracted") or {})

        reply = data.get("reply") or "Got it! What else can you tell me?"
        session.add_message("agent", reply)
        object.__setattr__(session, "pending_question", reply)

        if data.get("all_collected"):
            object.__setattr__(session, "state", ConversationState.AWAITING_SCOPE_CONFIRMATION)

        return session


# ------------------------------------------------------------------
# Module-level helpers (no state)
# ------------------------------------------------------------------

def _collected_context(session: ConversationSession) -> str:
    """Return a system-prompt suffix listing already-collected fields."""
    parts: list[str] = []
    if session.target_type:
        parts.append(f"target_type={session.target_type.value}")
    if session.target_name:
        parts.append(f"target_name={session.target_name!r}")
    if session.app_url:
        parts.append(f"target_url={session.app_url}")
    elif session.repo_ref:
        parts.append(f"target_url={session.repo_ref}")
    if session.environment_classification:
        parts.append(f"environment={session.environment_classification}")
    if session.requested_capabilities:
        parts.append(f"test_scope={[c.value for c in session.requested_capabilities]}")
    if session.forbidden_operations:
        parts.append(f"restrictions={session.forbidden_operations}")
    if not parts:
        return ""
    return "\n\nAlready collected: " + ", ".join(parts) + ". Do not re-ask for these."


def _merge_extracted(session: ConversationSession, extracted: dict[str, Any]) -> None:
    """Write non-null LLM-extracted fields into the session without overwriting with None."""
    if extracted.get("target_type"):
        try:
            object.__setattr__(session, "target_type", TargetType(extracted["target_type"]))
        except ValueError:
            session.warnings.append(
                f"Unrecognised target_type from model: {extracted['target_type']!r}"
            )

    if extracted.get("target_name"):
        object.__setattr__(session, "target_name", str(extracted["target_name"])[:255])

    target_url = extracted.get("target_url")
    if target_url:
        url_str = str(target_url)
        normalized_url = url_str.rstrip("/")
        if normalized_url.startswith("https://github.com/"):
            object.__setattr__(session, "repo_ref", normalized_url)
        elif url_str.startswith(("http://", "https://")):
            object.__setattr__(session, "app_url", url_str)
        else:
            object.__setattr__(session, "repo_ref", url_str[:500])

    if extracted.get("environment"):
        env = str(extracted["environment"]).lower().strip()
        if env != "production":
            object.__setattr__(session, "environment_classification", env)

    test_scope = extracted.get("test_scope")
    if test_scope and isinstance(test_scope, list):
        caps: list[TestCategory] = []
        for item in test_scope:
            try:
                caps.append(TestCategory(str(item)))
            except ValueError:
                session.warnings.append(f"Unrecognised test_scope value: {item!r}")
        if caps:
            object.__setattr__(session, "requested_capabilities", caps)

    restrictions = extracted.get("restrictions")
    if restrictions and isinstance(restrictions, list):
        items = [str(r).strip() for r in restrictions if str(r).strip()]
        if items:
            object.__setattr__(session, "forbidden_operations", items)


def _set_state(session: ConversationSession, state: ConversationState) -> ConversationSession:
    """Update session state and set the corresponding pending question."""
    question = _STATE_MESSAGES.get(state)
    object.__setattr__(session, "state", state)
    object.__setattr__(session, "pending_question", question)
    if question:
        session.add_message("agent", question)
    return session


def _parse_json_response(content: str) -> dict[str, Any]:
    """Strip optional markdown fences and parse JSON from the model response."""
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        end = next((i for i in range(len(lines) - 1, 0, -1) if lines[i].strip() == "```"), -1)
        inner = lines[1:end] if end > 0 else lines[1:]
        stripped = "\n".join(inner).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned non-JSON: {content[:300]!r}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Model JSON was not an object: {type(data)}")
    return data


_STATE_MESSAGES: dict[ConversationState, str] = {
    ConversationState.GENERATING_TEST_CASES: (
        "Scope confirmed. Test-case generation will begin shortly.\n"
        "You will be asked to review and approve the test cases before any scripts are generated."
    ),
    ConversationState.COMPLETED: "Session completed.",
    ConversationState.CANCELLED: "Session cancelled.",
    ConversationState.FAILED: "Session failed. Check warnings for details.",
}



