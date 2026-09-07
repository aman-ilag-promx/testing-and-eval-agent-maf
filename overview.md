# Testing and Evaluation Agent - Project Handover Overview

## 1. Purpose of This File

This file transfers the full working context of the Testing and Evaluation Agent project to a new Copilot chat.

The new chat must read this file before generating or changing any project file. The new chat must continue from the exact implementation point documented here and must not redesign the architecture without clearly identifying a conflict with `plan.md`.

## 2. Working Style Required From the New Chat

The user is manually pasting generated content into empty files in Visual Studio Code.

Follow these rules for every implementation response:

1. Work on one file at a time unless the user explicitly requests multiple files.
2. State the exact file path.
3. State whether the file already exists or is a new file.
4. If the file was not in the original skeleton, explicitly state that it is a new file added during implementation.
5. State whether the user should create the file, replace all content, or append content.
6. Provide complete file content from the first line to the final line.
7. Never provide partial code.
8. Never use ellipses, placeholder logic, omitted sections, or unfinished `TODO` blocks in implementation files.
9. Do not reference a local module that has not already been created unless the dependency is being generated in the same response.
10. Include commands to validate syntax, imports, formatting, linting, typing, and expected behavior.
11. Validate code before presenting it.
12. For Python files, scan for malformed annotations before responding.
13. Do not accidentally join a return annotation and docstring.
14. Use the following correct syntax:

```python
def example(values: list[str]) -> list[str]:
    """Describe the function."""
```

15. Never generate malformed syntax like:

```python
def example(values: list[str]) -> list[str]"""Invalid syntax."""
```

16. Do not move to the next file if the current file contains a known syntax or integration error.
17. Keep generated and approved artifacts separate.
18. Preserve every human approval checkpoint.
19. Generated Playwright scripts must never execute automatically.
20. Keep responses focused. Provide only the requested file content and validation commands when the user asks to continue coding.

## 3. Project Definition

The project is a Testing and Evaluation Agent built around Microsoft Agent Framework, Microsoft Foundry models, Playwright MCP, and Playwright Test.

The agent is not only a Playwright script generator. The intended system manages a controlled testing lifecycle:

1. Accept an original user request, implementation plan, or implementation artifact.
2. Generate structured and traceable test cases.
3. Stop for human approval of the test cases.
4. Generate Playwright Test TypeScript scripts only from approved test cases.
5. Stop for human approval of the generated scripts.
6. Execute approved scripts only through a separate execution trigger.
7. Collect deterministic evidence such as results, screenshots, traces, accessibility information, console output, and network information.
8. Evaluate the implementation using configurable rubrics.
9. Compare the original request and approved plan against the implementation and observed evidence.
10. Generate final reports, gap analysis, and improvement recommendations.
11. Require human review before downstream changes.

## 4. Manager Task Definition

The agent must support the following testing capabilities as separate skills.

### 4.1 Smoke Testing

Verify that:

- Expected components exist.
- Components load successfully.
- Required data is available.
- Components are included in the overall solution.
- Essential user paths work.

### 4.2 Integration and Self-Testing

Verify that:

- The complete process still works.
- Skills and agents executed successfully.
- Workflows respected approval checkpoints.
- Required artifacts were created.
- Errors are classified by likely source.
- Suggestions are produced to improve a skill or process when issues occur.

Future scheduled self-testing may be supported, but scheduling is not part of the initial vertical slice.

### 4.3 Evaluation Testing

Generate and apply evaluations for AI-based features.

Evaluation standards are not finalized and must remain configurable for future alignment with Swarangi and the QA team.

The architecture must support:

- Rubrics.
- Datasets.
- Baselines.
- Evidence-based scores.
- Rationale.
- Confidence or uncertainty.
- Recommendations.
- Persisted evaluation results.

### 4.4 Plan Versus Implementation Testing

Independently compare:

- The original user request.
- The approved implementation plan.
- Implementation artifacts.
- Test execution results.
- Evaluation evidence.
- The final observable outcome.

Classify each requirement as:

- Fully implemented.
- Partially implemented.
- Missing.
- Changed.
- Additional unrequested behavior.
- Not verifiable.

The agent may recommend changes but must not automatically modify the implementation.

### 4.5 UI Testing

Validate Code Apps and Web Apps across:

- Functionality.
- Visual design.
- Responsiveness.
- Performance.
- Usability.
- Accessibility.

Playwright MCP assists with exploration, page understanding, locator discovery, accessibility snapshots, and screenshots.

Playwright Test with TypeScript remains the deterministic execution layer.

### 4.6 Generate Test Cases

Generate test cases from an implementation plan, original request, or implementation artifact.

Each test case should include:

- Unique identifier.
- Title.
- Description.
- Source requirement references.
- Category.
- Priority.
- Preconditions.
- Test data.
- Ordered steps.
- Expected results.
- Automation suitability.
- Evidence requirements.
- Safety considerations.
- Approval status.
- Traceability metadata.

### 4.7 Generate Playwright Scripts

Generate TypeScript Playwright Test scripts from approved test cases.

Generated scripts must:

- Use `@playwright/test`.
- Map to source test-case IDs.
- Prefer accessible locators.
- Use Playwright assertions.
- Avoid arbitrary waits.
- Avoid embedded credentials.
- Be stored in `tests/generated/`.
- Remain unexecuted until reviewed, approved, promoted to an approved test directory, and separately triggered.

### 4.8 Future Azure DevOps MCP Integration

ADO MCP is outside the initial implementation.

Future integration may support:

- Reading ADO test cases.
- Reading ADO test suites.
- Mapping repository scripts to ADO cases.
- Synchronizing execution results and evidence.

Do not implement ADO MCP in the current vertical slice.

## 5. Core Technical Architecture

### 5.1 Python

Python 3.11 or newer is used for:

- Microsoft Agent Framework orchestration.
- Microsoft Foundry model access.
- Pydantic schemas.
- Workflows.
- Approval checkpoints.
- Deterministic tools and adapters.
- Evaluators.
- Report generation.

### 5.2 TypeScript

TypeScript and Playwright Test are used for deterministic browser testing.

### 5.3 Microsoft Agent Framework

Microsoft Agent Framework is the orchestration layer for:

- Input handling.
- Model-backed reasoning.
- Skill selection.
- Workflow delegation.
- Approval-aware control flow.

Do not treat Microsoft Agent Framework as `azure-ai-agents`.

The dependency direction selected for the project is:

```text
agent-framework>=1.0.0,<2.0.0
```

### 5.4 Microsoft Foundry

A Microsoft Foundry model deployment may be used for:

- Understanding plans.
- Generating draft test cases.
- Generating draft Playwright scripts.
- Explaining evidence.
- Evaluating AI features.
- Comparing plan and implementation.

Model output is not deterministic execution evidence and must be validated before persistence or downstream use.

### 5.5 Playwright MCP

Playwright MCP is intended for:

- Browser exploration.
- Page-structure inspection.
- Locator discovery.
- Accessibility snapshots.
- Screenshot assistance.
- Test-generation support.

Playwright MCP must not replace Playwright Test execution or bypass approvals.

## 6. Mandatory Approval Gates

### Checkpoint A: Test-Case Approval

Generated test cases require human approval before script generation.

### Checkpoint B: Script Approval

Generated Playwright scripts require human approval before execution.

### Checkpoint C: Evaluation Approval

Evaluation findings require human review before downstream implementation proposals.

### Checkpoint D: External-System Approval

Future App Factory, Azure DevOps, or other external-system actions require explicit human approval.

No agent, workflow, tool, or skill may bypass these gates.

## 7. Safety Boundaries

1. Never execute generated scripts automatically.
2. Never test production by default.
3. Never perform destructive actions without explicit approval.
4. Never modify the tested application.
5. Never commit secrets.
6. Never embed credentials in generated tests.
7. Never silently promote generated files into approved directories.
8. Never claim a test passed without deterministic execution evidence.
9. Never claim plan alignment without traceable comparison evidence.
10. Never hide failures, uncertainty, missing inputs, or missing evidence.
11. Never overwrite approved artifacts with drafts.
12. Never activate ADO MCP in the initial implementation.
13. Never continue through a dependent unsafe workflow step after a blocking failure.

## 8. First Working Vertical Slice

```text
Original request or implementation plan
    -> Generate structured test cases
    -> Human test-case approval
    -> Generate Playwright scripts
    -> Human script approval
    -> Promote approved script to an approved test directory
    -> Separate Playwright smoke-test execution
    -> Collect evidence
    -> Evaluate results
    -> Human evaluation review
    -> Compare plan against implementation
    -> Generate final report
```

## 9. Current Repository Structure

The following tree includes original files, files already implemented, and planned files.

```text
Testing and Eval Agent - MAF/
|
|-- README.md                              [EXISTING, content completed]
|-- AGENTS.md                              [EXISTING, content completed]
|-- plan.md                                [EXISTING, authoritative project plan]
|-- overview.md                            [NEW, this handover file]
|-- pyproject.toml                         [EXISTING, content completed]
|-- requirements.txt                       [EXISTING, content completed]
|-- package.json                           [EXISTING, content completed]
|-- package-lock.json                      [GENERATED by npm]
|-- playwright.config.ts                   [EXISTING, content completed]
|-- tsconfig.json                          [NEW, content completed]
|-- .env.example                           [EXISTING, content completed]
|-- .env                                   [LOCAL, copied from .env.example]
|-- .gitignore                             [EXISTING, content completed]
|-- .mcp.json.example                      [EXISTING, content completed]
|
|-- .vscode/
|   |-- mcp.json                           [LOCAL workspace MCP configuration]
|
|-- src/
|   |-- __init__.py                        [PLANNED NEW FILE]
|   |-- config.py                          [NEW, content provided]
|   |-- main.py                            [PLANNED NEW FILE]
|   |
|   |-- models/
|   |   |-- __init__.py                    [NEW, currently created]
|   |   |-- enums.py                       [NEW, currently created]
|   |   |-- common.py                      [NEW, currently created]
|   |   |-- test_cases.py                  [NEW, currently created]
|   |   |-- playwright.py                  [NEW, currently created]
|   |   |-- evaluation.py                  [NEW, last generated file]
|   |   |-- plan_comparison.py             [NEXT FILE]
|   |   |-- reports.py                     [PLANNED NEW FILE]
|   |   |-- workflow.py                    [PLANNED NEW FILE]
|   |   |-- skills.py                      [PLANNED NEW FILE]
|   |
|   |-- tools/
|   |   |-- __init__.py                    [PLANNED NEW FILE]
|   |   |-- artifact_store.py              [PLANNED NEW FILE]
|   |   |-- skill_loader.py                [PLANNED NEW FILE]
|   |   |-- approval_store.py              [PLANNED NEW FILE]
|   |   |-- playwright_runner.py           [PLANNED NEW FILE]
|   |   |-- report_writer.py               [PLANNED NEW FILE]
|   |
|   |-- evaluators/
|   |   |-- __init__.py                    [PLANNED NEW FILE]
|   |   |-- rubric_loader.py               [PLANNED NEW FILE]
|   |   |-- result_evaluator.py            [PLANNED NEW FILE]
|   |   |-- plan_comparator.py             [PLANNED NEW FILE]
|   |
|   |-- workflows/
|   |   |-- __init__.py                    [PLANNED NEW FILE]
|   |   |-- approval_workflow.py           [PLANNED NEW FILE]
|   |   |-- test_generation_workflow.py    [PLANNED NEW FILE]
|   |   |-- script_generation_workflow.py  [PLANNED NEW FILE]
|   |   |-- evaluation_workflow.py         [PLANNED NEW FILE]
|   |
|   |-- agents/
|       |-- __init__.py                    [PLANNED NEW FILE]
|       |-- model_client.py                [PLANNED NEW FILE]
|       |-- instructions.py                [PLANNED NEW FILE]
|       |-- testing_agent.py               [PLANNED NEW FILE]
|
|-- skills/
|   |-- smoke-testing/
|   |   |-- SKILL.md                       [EXISTING EMPTY FILE, content pending]
|   |-- integration-self-testing/
|   |   |-- SKILL.md                       [EXISTING EMPTY FILE, content pending]
|   |-- evaluation-testing/
|   |   |-- SKILL.md                       [EXISTING EMPTY FILE, content pending]
|   |-- plan-vs-implementation/
|   |   |-- SKILL.md                       [EXISTING EMPTY FILE, content pending]
|   |-- ui-testing/
|   |   |-- SKILL.md                       [EXISTING EMPTY FILE, content pending]
|   |-- generate-test-cases/
|   |   |-- SKILL.md                       [EXISTING EMPTY FILE, content pending]
|   |-- generate-playwright-scripts/
|       |-- SKILL.md                       [EXISTING EMPTY FILE, content pending]
|
|-- evals/
|   |-- datasets/
|   |   |-- .gitkeep
|   |-- rubrics/
|   |   |-- .gitkeep
|   |   |-- default-evaluation-rubric.yaml [PLANNED NEW FILE]
|   |-- baselines/
|   |   |-- .gitkeep
|   |-- results/
|       |-- .gitkeep
|
|-- fixtures/
|   |-- app-factory/
|   |   |-- .gitkeep
|   |-- sample-app/
|       |-- .gitkeep
|
|-- specs/
|   |-- generated/
|   |   |-- .gitkeep
|   |-- approved/
|       |-- .gitkeep
|
|-- tests/
|   |-- conftest.py                        [PLANNED NEW FILE]
|   |-- test_models.py                     [PLANNED NEW FILE]
|   |-- test_artifact_store.py             [PLANNED NEW FILE]
|   |-- test_approval_workflow.py           [PLANNED NEW FILE]
|   |
|   |-- generated/
|   |   |-- .gitkeep
|   |-- smoke/
|   |   |-- .gitkeep
|   |   |-- application-load.spec.ts       [PLANNED NEW FILE]
|   |-- integration/
|   |   |-- .gitkeep
|   |-- ui/
|       |-- .gitkeep
|
|-- reports/
|   |-- .gitkeep
|
|-- traces/
|   |-- .gitkeep
|
|-- screenshots/
|   |-- .gitkeep
|
|-- docs/
    |-- ARCHITECTURE.md
    |-- POC_SCOPE.md
    |-- APP_FACTORY_INTEGRATION_PROPOSAL.md
```

## 10. Files Already Implemented

### Root Files

The following root files have received content:

```text
README.md
AGENTS.md
pyproject.toml
requirements.txt
package.json
playwright.config.ts
tsconfig.json
.env.example
.gitignore
.mcp.json.example
```

### Python Files

The following Python files have been created or provided:

```text
src/config.py
src/models/__init__.py
src/models/enums.py
src/models/common.py
src/models/test_cases.py
src/models/playwright.py
src/models/evaluation.py
```

## 11. Important Validation Warning

Earlier chat responses accidentally generated malformed Python return annotations where a docstring was joined to a return type.

Example of the error:

```python
def validate_items(value: list[str]) -> list[str]"""Invalid."""
```

Every current Python file must be checked locally before the new chat assumes that the model layer is valid.

Run this malformed-annotation scan from the repository root:

```powershell
$malformedPatterns = @(
    'list\[str\]"""',
    'list\[UUID\]"""',
    'dict\[.*\]"""',
    'str"""',
    'Self"""',
    'Path"""',
    'UUID"""'
)

$matches = Get-ChildItem .\src -Recurse -Filter *.py |
    Select-String -Pattern $malformedPatterns

if ($matches) {
    $matches
    throw "Malformed return annotation detected."
}

Write-Host "No malformed return annotations found."
```

Run complete Python compilation:

```powershell
python -m compileall -q .\src

if ($LASTEXITCODE -ne 0) {
    throw "Python compilation failed."
}

Write-Host "All current Python files compiled successfully."
```

Run quality checks:

```powershell
python -m ruff format .\src
python -m ruff check .\src
python -m ruff format --check .\src
python -m mypy .\src
```

The new chat must fix any existing file that fails these checks before adding dependent files.

## 12. Model Layer Responsibilities

### `src/models/enums.py`

Contains shared string enums including:

- Test categories.
- Priorities.
- Approval states.
- Artifact types and states.
- Workflow stages and outcomes.
- Execution statuses.
- Browser names.
- Evidence types.
- Failure sources.
- Evaluation outcomes.
- Requirement statuses.
- Severity values.
- Report formats.

### `src/models/common.py`

Contains shared models including:

- `AgentBaseModel`.
- `ArtifactReference`.
- `EvidenceReference`.
- `WarningDetail`.
- `ErrorDetail`.
- `ApprovalRecord`.
- `ArtifactMetadata`.
- `OperationResult`.

### `src/models/test_cases.py`

Contains:

- `ImplementationInput`.
- `TestStep`.
- `TestCase`.
- `TestCaseGenerationRequest`.
- `TestCaseCollection`.

### `src/models/playwright.py`

Contains:

- `PlaywrightGenerationConstraints`.
- `PlaywrightScriptGenerationRequest`.
- `GeneratedPlaywrightScript`.
- `PlaywrightExecutionRequest`.
- `PlaywrightExecutionResult`.

### `src/models/evaluation.py`

Contains:

- `EvaluationScale`.
- `EvaluationCriterion`.
- `EvaluationRubric`.
- `EvaluationRequest`.
- `CriterionEvaluation`.
- `EvaluationResult`.

The file content was most recently generated, but it must pass local compilation and malformed-annotation scanning before dependent work begins.

## 13. Exact Next File

The next file is:

```text
src/models/plan_comparison.py
```

File status:

```text
NEW FILE
```

This file was not listed individually in the original repository skeleton. It belongs in the existing `src/models/` directory.

The file should define complete models for:

- A source requirement captured from the original request or approved plan.
- Evidence mapped to a requirement.
- A finding that classifies implementation status.
- Gap impact and severity.
- Suggested improvements.
- A plan-comparison request.
- A complete plan-comparison result.
- Artifact metadata validation requiring `ArtifactType.PLAN_COMPARISON`.
- Unique requirement identifiers.
- Evidence requirements for verifiable implementation claims.
- Validation that non-verifiable findings do not pretend to have conclusive evidence.

The file should rely only on modules already created:

```python
from src.models.common import ...
from src.models.enums import ...
from src.models.test_cases import ImplementationInput
from src.models.playwright import PlaywrightExecutionResult
from src.models.evaluation import EvaluationResult
```

Do not import `reports.py`, `workflow.py`, or `skills.py` because those files do not exist yet.

## 14. Remaining Implementation Order

Continue in this exact order to minimize circular imports and undefined dependencies.

### Phase 1: Complete Shared Models

```text
1. src/models/plan_comparison.py       [NEXT]
2. src/models/reports.py
3. src/models/workflow.py
4. src/models/skills.py
5. Replace src/models/__init__.py with finalized exports
6. Run full model-layer compilation, lint, formatting, typing, and validation tests
```

### Phase 2: Deterministic Tools

```text
7. src/tools/__init__.py
8. src/tools/artifact_store.py
9. src/tools/skill_loader.py
10. src/tools/approval_store.py
11. src/tools/playwright_runner.py
12. src/tools/report_writer.py
```

### Phase 3: Evaluators

```text
13. src/evaluators/__init__.py
14. src/evaluators/rubric_loader.py
15. src/evaluators/result_evaluator.py
16. src/evaluators/plan_comparator.py
```

### Phase 4: Workflows

```text
17. src/workflows/__init__.py
18. src/workflows/approval_workflow.py
19. src/workflows/test_generation_workflow.py
20. src/workflows/script_generation_workflow.py
21. src/workflows/evaluation_workflow.py
```

### Phase 5: Microsoft Agent Framework Integration

```text
22. src/__init__.py
23. src/agents/__init__.py
24. src/agents/model_client.py
25. src/agents/instructions.py
26. src/agents/testing_agent.py
27. src/main.py
```

### Phase 6: Skill Instructions

These files already exist but are empty. Replace their content one file at a time.

```text
28. skills/generate-test-cases/SKILL.md
29. skills/generate-playwright-scripts/SKILL.md
30. skills/smoke-testing/SKILL.md
31. skills/integration-self-testing/SKILL.md
32. skills/ui-testing/SKILL.md
33. skills/evaluation-testing/SKILL.md
34. skills/plan-vs-implementation/SKILL.md
```

### Phase 7: Evaluation Asset

```text
35. evals/rubrics/default-evaluation-rubric.yaml
```

### Phase 8: Automated Tests

```text
36. tests/conftest.py
37. tests/test_models.py
38. tests/test_artifact_store.py
39. tests/test_approval_workflow.py
40. tests/smoke/application-load.spec.ts
```

### Phase 9: End-to-End Validation

Validate:

- Python compilation.
- Ruff formatting.
- Ruff linting.
- Mypy typing.
- Pytest unit tests.
- TypeScript compilation.
- Playwright test discovery.
- Generated-test execution blocking.
- Approval-gate enforcement.
- Artifact path safety.
- Model serialization round trips.
- One separately triggered approved smoke test.

## 15. Planned File Count From This Handover Point

After `overview.md`, the implementation plan contains 34 main remaining source, skill, configuration, and test files after the currently generated model files, plus the final update to `src/models/__init__.py`.

The exact total may change only if a verified framework requirement demands an additional adapter or package file. Any such addition must be clearly labeled as a new file not present in this handover skeleton.

## 16. Current Environment and Setup Commands

### Python Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip check
```

### Node and Playwright Setup

```powershell
npm install
npm run playwright:install
npm run typecheck
npm run test:list
npm run check
```

### Environment File

```powershell
Copy-Item .env.example .env
```

Do not add real credentials until the Foundry model-client file is implemented.

### Azure CLI Authentication

The preferred local development authentication mode is:

```dotenv
MAF_AUTH_MODE=azure_cli
```

Sign-in command:

```powershell
az login
```

### MCP Workspace Configuration

The local workspace file is:

```text
.vscode/mcp.json
```

The template is:

```text
.mcp.json.example
```

Playwright MCP remains disabled in `.env` until the MCP integration and safety controls are implemented.

## 17. Important Configuration Defaults

The `.env.example` was designed with safe defaults:

```dotenv
REQUIRE_TEST_CASE_APPROVAL=true
REQUIRE_SCRIPT_APPROVAL=true
REQUIRE_EVALUATION_APPROVAL=true
ALLOW_LIVE_TEST_EXECUTION=false
ALLOW_DESTRUCTIVE_TESTS=false
PLAYWRIGHT_MCP_ENABLED=false
ADO_MCP_ENABLED=false
```

Generated and runtime directories include:

```dotenv
SKILLS_DIR=skills
GENERATED_SPECS_DIR=specs/generated
APPROVED_SPECS_DIR=specs/approved
GENERATED_TESTS_DIR=tests/generated
REPORTS_DIR=reports
TRACES_DIR=traces
SCREENSHOTS_DIR=screenshots
EVAL_DATASETS_DIR=evals/datasets
EVAL_RUBRICS_DIR=evals/rubrics
EVAL_BASELINES_DIR=evals/baselines
EVAL_RESULTS_DIR=evals/results
```

## 18. Artifact Separation Rules

```text
Draft test cases:
    specs/generated/

Approved test cases:
    specs/approved/

Generated Playwright scripts:
    tests/generated/

Approved smoke tests:
    tests/smoke/

Approved integration tests:
    tests/integration/

Approved UI tests:
    tests/ui/

Evaluation results:
    evals/results/

Reports:
    reports/

Traces:
    traces/

Screenshots:
    screenshots/
```

Generated scripts must not execute directly from `tests/generated/`.

## 19. Coding Standards

### Python

- Python 3.11 or newer.
- Full type hints for public functions and methods.
- Pydantic at workflow and adapter boundaries.
- `pathlib.Path` for paths.
- Timezone-aware UTC timestamps.
- Structured errors and warnings.
- No global mutable state.
- No silent broad exception handling.
- No hard-coded secrets, endpoints, model names, or repository paths.
- Deterministic operations belong in `src/tools/`.
- Model reasoning must not replace deterministic behavior.

### TypeScript and Playwright

- Strict TypeScript.
- `@playwright/test`.
- Accessible locators preferred in this order:
  1. `getByRole`
  2. `getByLabel`
  3. `getByPlaceholder`
  4. `getByText`
  5. `getByTestId`
  6. Stable CSS as a fallback
  7. XPath only as a last resort
- No `page.waitForTimeout()` as normal synchronization.
- No embedded credentials.
- Each test maps to a test-case ID.
- Tests remain independent.

## 20. Definition of Done for the Initial Version

The first implementation is complete when:

1. An original request or implementation plan can be accepted.
2. Structured test cases can be generated and stored.
3. Test-case approval is enforced.
4. Playwright scripts can be generated only from approved test cases.
5. Generated scripts can be stored safely.
6. Script approval is enforced.
7. Approved scripts can be promoted safely.
8. An approved smoke test can be executed through a separate trigger.
9. Execution evidence can be collected.
10. Results can be evaluated against an approved rubric.
11. Evaluation review is enforced.
12. The original request and approved plan can be compared with the implementation.
13. A structured final report can be generated.
14. Failure paths are preserved and classified.
15. Unit tests verify approvals, paths, serialization, transitions, and failures.
16. No generated script executes without approval.
17. No secret is committed.
18. All Python and TypeScript validation checks pass.

## 21. Instruction to the New Chat

Start by reading:

```text
plan.md
overview.md
AGENTS.md
README.md
```

Then run or ask the user to run the current Python validation checks.

If the existing model files compile and pass malformed-annotation scanning, continue with exactly one file:

```text
src/models/plan_comparison.py
```

The response must begin with:

```text
FILE STATUS: NEW FILE
FILE PATH: src/models/plan_comparison.py
ACTION: CREATE THIS FILE
ORIGINAL PLAN UPDATE: This individual implementation file was not listed in the original skeleton and belongs under the existing src/models directory.
```

Provide the complete file and validation commands in the same response. Do not generate any other implementation file in that step.
