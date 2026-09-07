"""Quick pipeline smoke test — generate test cases + scripts for the GitHub repo."""
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.stdout.reconfigure(encoding="utf-8")

from src.config import get_settings
from src.agents.testing_agent import create_testing_agent
from src.models.test_cases import ImplementationInput, TestCaseGenerationRequest, TestCaseCollection
from src.models.playwright import PlaywrightScriptGenerationRequest
from src.models.enums import TestCategory

settings = get_settings()
settings.ensure_output_directories()
agent = create_testing_agent(settings=settings)
run_id = uuid4()

# --- Step 1: Generate test cases ---
print("[Testing]: Generating test cases...")
impl = ImplementationInput(
    title="Smoke test - what-i-test",
    original_user_request=(
        "Target: what-i-test generic_repo at "
        "https://github.com/aman-ilag-promx/what-i-test.git, "
        "development environment, smoke test scope."
    ),
    target_scope="smoke tests for what-i-test (development)",
    source_references=["https://github.com/aman-ilag-promx/what-i-test.git"],
)
req = TestCaseGenerationRequest(
    run_id=run_id,
    implementation_input=impl,
    requested_categories=[TestCategory.SMOKE],
)
tc_result = agent.generate_test_cases(req)
tc_arts = tc_result.produced_artifacts or []

if not tc_arts:
    print("ERROR: Test case generation produced no artifacts.")
    print("Errors:", tc_result.errors)
    sys.exit(1)

data = json.loads(Path(tc_arts[0].path).read_text(encoding="utf-8"))
cases = data.get("test_cases", [])
print(f"[Testing]: Generated {len(cases)} test case(s):\n")
for i, tc in enumerate(cases, 1):
    cat = tc.get("category", "").upper()
    title = tc.get("title", "(untitled)")
    priority = tc.get("priority", "?")
    steps = len(tc.get("steps", []))
    print(f"  {i}. [{cat}] {title}")
    print(f"     Priority: {priority}  |  Steps: {steps}")

print()
print(f"  Saved: {tc_arts[0].path}")

# --- Step 2: Generate Playwright scripts ---
print()
print("[Testing]: Generating Playwright scripts...")
collection = TestCaseCollection.model_validate_json(
    Path(tc_arts[0].path).read_text(encoding="utf-8")
)
from src.models.enums import ApprovalStatus
# Mark all test cases approved so the script generation request passes validation
for tc in collection.test_cases:
    object.__setattr__(tc, "approval_status", ApprovalStatus.APPROVED)

script_req = PlaywrightScriptGenerationRequest(
    run_id=run_id,
    source_collection_id=tc_arts[0].artifact_id,
    approved_test_cases=collection.test_cases,
    approval_reference_id=uuid4(),
)
sc_result = agent.generate_playwright_scripts(script_req)
sc_arts = sc_result.produced_artifacts or []

if sc_arts:
    print(f"[Testing]: Scripts saved → {sc_arts[0].path}")
    print()
    print("[Testing]: Script preview (first 30 lines):")
    lines = Path(sc_arts[0].path).read_text(encoding="utf-8").splitlines()
    for line in lines[:30]:
        print("  " + line)
else:
    print("[Testing]: No script artifacts returned.")

# --- Summary ---
print()
print("=" * 60)
print("[Done]: Pipeline complete!")
print()
print(f"  Test cases : {tc_arts[0].path}")
if sc_arts:
    print(f"  Scripts    : {sc_arts[0].path}")
print()
print("Live execution is disabled by default.")
print("To run tests manually:")
if sc_arts:
    print(f"  npx playwright test {sc_arts[0].path}")
print("=" * 60)
