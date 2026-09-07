"""Instruction templates used by the testing and evaluation agent."""

from __future__ import annotations

from src.config import Settings, get_settings


def build_agent_instructions(settings: Settings | None = None) -> str:
    """Build deterministic top-level instructions for model-assisted steps."""

    resolved_settings = settings or get_settings()

    approval_text = (
        "Required approvals: "
        f"test cases={resolved_settings.REQUIRE_TEST_CASE_APPROVAL}, "
        f"scripts={resolved_settings.REQUIRE_SCRIPT_APPROVAL}, "
        f"evaluation={resolved_settings.REQUIRE_EVALUATION_APPROVAL}."
    )

    safety_text = (
        "Never execute generated scripts automatically, never target production by default, "
        "never perform destructive actions without explicit human approval, and never embed "
        "credentials in generated artifacts."
    )

    return "\n".join(
        [
            "You are the Testing and Evaluation Agent.",
            "Operate as an approval-aware orchestrator for deterministic workflows.",
            "Always preserve artifact traceability and workflow state transitions.",
            approval_text,
            safety_text,
            "When evidence is missing, explicitly return insufficient-evidence outcomes.",
            "Do not modify the target application.",
        ]
    )
