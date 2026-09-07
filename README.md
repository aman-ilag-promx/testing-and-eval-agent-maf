# Testing and Evaluation Agent

A Microsoft Agent Framework based agent for generating test cases, creating Playwright scripts, executing approved browser tests, evaluating results, and comparing completed implementations against their original requirements.

The project combines:

- Microsoft Agent Framework for agent orchestration
- Microsoft Foundry models for reasoning and content generation
- Playwright MCP for browser exploration and test-generation assistance
- Playwright Test with TypeScript for deterministic browser automation
- Python and Pydantic for workflows, validation, approvals, evaluation, and reporting

## Project Status

Current status: conversational testing pipeline implemented. GitHub MCP evidence support is disabled by default until a token is configured locally. Playwright MCP browser exploration is an optional observation layer; Playwright Test remains the execution layer.

The agent accepts natural-language test requests through the CLI, uses the configured Microsoft Foundry model to collect missing details, generates traceable test artifacts, and preserves mandatory human approval before execution.

## Local Configuration

Create a local `.env` file from the tracked template before running the agent. Do not commit `.env`; it is ignored by Git. Keep `MAF_PROJECT_ENDPOINT`, `MAF_MODEL_NAME`, `MAF_MODEL_API_KEY`, and `GITHUB_MCP_TOKEN` blank in `.env.example`.

```powershell
Copy-Item .env.example .env
```

Complete these `.env` fields for live Foundry model generation:

- `MAF_PROJECT_ENDPOINT`: Your Microsoft Foundry project endpoint.
- `MAF_MODEL_NAME`: The deployment name in that Foundry project.
- `MAF_AUTH_MODE`: Set to `azure_cli` or `api_key`.
- `MAF_MODEL_API_KEY`: Required only when `MAF_AUTH_MODE=api_key`; leave it blank when using `azure_cli`.

For `azure_cli` authentication, sign in before starting the agent:

```powershell
az login
```

Optional integrations require their corresponding fields only when enabled:

- GitHub MCP: set `GITHUB_MCP_ENABLED=true` and provide `GITHUB_MCP_TOKEN`. Keep `GITHUB_MCP_URL` at the template's read-only hosted endpoint. Set `GITHUB_MCP_ALLOW_PRIVATE_REPOSITORIES=true` only when private repository observations are needed.
- Playwright MCP: set `PLAYWRIGHT_MCP_ENABLED=true`; the provided `PLAYWRIGHT_MCP_COMMAND` and `PLAYWRIGHT_MCP_ARGS` defaults run the official server through `npx`. Set `PLAYWRIGHT_MCP_URL` only when using a managed MCP endpoint instead.
- Azure DevOps MCP: not supported in the current version. Leave `ADO_MCP_ENABLED=false` and `ADO_MCP_URL` blank.
- Live browser execution: set `TARGET_BASE_URL` to an approved non-production URL and set `ALLOW_LIVE_TEST_EXECUTION=true`. Leave `ALLOW_DESTRUCTIVE_TESTS=false` unless explicitly authorized.

## Quick Start

```powershell
.venv\Scripts\python.exe -m src.main chat
```

Describe the request naturally, for example:

```text
Smoke test the GitHub repository https://github.com/owner/repository.git in staging. Call it repository-staging.
```

The agent collects only missing information, generates draft test cases, pauses for approval, generates a Playwright draft, pauses again, then promotes an approved script into the appropriate execution folder. It reports `Live execution is disabled` unless `ALLOW_LIVE_TEST_EXECUTION=true` is explicitly configured for a permitted non-production target.

## MCP Evidence

GitHub MCP is optional and read-only. It uses GitHub's hosted `https://api.githubcopilot.com/mcp/readonly` endpoint, so Docker and WSL are not required. When enabled, it can collect repository root contents, commits, pull requests, issues, and code-search observations for public repositories and authorized private repositories. It cannot modify a repository, create comments, issues, or pull requests; merge branches; dispatch workflows; or access secrets.

For this standalone Python CLI, configure a fine-grained GitHub token locally in `.env`, set `GITHUB_MCP_ENABLED=true`, and retain the hosted URL from `.env.example`. Use only the minimum read permissions for Metadata, Contents, Pull requests, and Issues. `GITHUB_MCP_TOKEN` is used only at runtime and is never displayed by `show-config` or persisted in artifacts. OAuth browser sign-in is supported by compatible MCP hosts such as VS Code, but it has not been implemented in this CLI.

Playwright MCP is also optional and observation-only. Set `PLAYWRIGHT_MCP_ENABLED=true` to run the official `@playwright/mcp` server through `npx`; the agent will navigate to a browser URL and collect a page snapshot before generation. It is not restricted to web-app target labels, but it requires an HTTP or HTTPS browser target. Neither MCP integration produces deterministic pass/fail results. Only the separately approved Playwright Test execution does that.

## Output Locations

- `specs/generated/`: draft test-case collections
- `specs/approved/`: approved test-case collections
- `tests/generated/`: unapproved Playwright drafts
- `tests/smoke/`, `tests/integration/`, `tests/ui/`: approved executable scripts
- `reports/`: runner and final reports
- `evals/results/`: evaluation results awaiting review
- `workspaces/`: isolated targets, runs, reusable assets, and resumable sessions

The first working version will implement the following vertical slice:

1. Accept an implementation plan or requirement.
2. Generate structured test cases.
3. Request human approval for the generated test cases.
4. Generate Playwright TypeScript scripts from approved test cases.
5. Request human approval for the generated scripts.
6. Execute approved Playwright tests through a separate trigger.
7. Collect execution evidence.
8. Evaluate the results.
9. Compare the original plan with the completed implementation.
10. Generate a final report.

Azure DevOps MCP integration is planned for a later version and is not part of the initial implementation.

## Project Objectives

The Testing and Evaluation Agent is designed to support the complete testing lifecycle of an implementation.

The agent should be able to:

- Understand an implementation plan
- Generate traceable test cases
- Organize tests by testing category
- Generate Playwright Test scripts
- Preserve human approval checkpoints
- Run approved tests through a separate execution process
- Collect screenshots, traces, and execution results
- Evaluate AI-based and deterministic functionality
- Compare the implementation with the original user request
- Identify missing, partial, changed, or additional behavior
- Generate evidence-based reports
- Recommend improvements without automatically modifying the implementation

## Testing Skills

Testing behavior is divided into separate instruction-based skills.

Each skill is stored under:

`skills/<skill-name>/SKILL.md`

### Smoke Testing

The smoke-testing skill verifies that critical parts of a solution are available and operational.

It checks whether:

- Expected components exist
- Required pages load
- Required data is available
- Essential navigation works
- Components are included in the overall solution
- Critical user paths can be completed

Smoke tests should be fast, repeatable, independent, and non-destructive.

Skill location:

`skills/smoke-testing/SKILL.md`

### Integration and Self-Testing

The integration and self-testing skill verifies whether connected components and the testing workflow work correctly.

It checks whether:

- The complete process still works
- Skills were selected correctly
- Agent operations completed successfully
- Tools returned valid results
- Approval checkpoints were respected
- Required artifacts were created
- Errors occurred during execution
- Failures originated from the application, test, tool, skill, model output, or workflow

Self-testing may suggest improvements to skills and workflows.

The skill must not automatically rewrite or activate a skill.

Skill location:

`skills/integration-self-testing/SKILL.md`

### Evaluation Testing

The evaluation-testing skill evaluates AI-based features and agent-generated outputs.

The evaluation system should support:

- Configurable rubrics
- Evaluation datasets
- Baseline expectations
- Evidence-based scoring
- Evaluation rationale
- Confidence or uncertainty
- Improvement recommendations
- Result persistence

Evaluation standards will remain configurable so that they can be aligned with the QA team.

Skill location:

`skills/evaluation-testing/SKILL.md`

### Plan Versus Implementation Testing

The plan-versus-implementation skill compares the intended implementation with the completed result.

It considers:

- The original user request
- The approved implementation plan
- Generated or modified artifacts
- Test execution results
- Evaluation evidence
- The final observable result

Each requirement may be classified as:

- Fully implemented
- Partially implemented
- Missing
- Changed
- Additional unrequested behavior
- Not verifiable

The skill may recommend improvements but must not automatically modify the implementation.

Skill location:

`skills/plan-vs-implementation/SKILL.md`

### UI Testing

The UI-testing skill validates Code Apps and Web Apps across multiple quality areas.

Supported UI testing areas include:

- Functionality
- Visual design
- Responsiveness
- Performance
- Usability
- Accessibility

Playwright MCP may assist with browser exploration, locator discovery, screenshots, page-structure inspection, and accessibility inspection.

Playwright Test is used for repeatable execution.

Skill location:

`skills/ui-testing/SKILL.md`

### Generate Test Cases

The generate-test-cases skill creates structured test cases from an implementation plan, user requirement, or implementation artifact.

Generated test cases should include:

- Test-case identifier
- Title
- Description
- Source requirement
- Test category
- Priority
- Preconditions
- Test data
- Test steps
- Expected results
- Automation suitability
- Required evidence
- Safety considerations
- Traceability metadata
- Approval status

Generated test cases are saved under:

`specs/generated/`

Approved test cases are saved under:

`specs/approved/`

Skill location:

`skills/generate-test-cases/SKILL.md`

### Generate Playwright Scripts

The generate-playwright-scripts skill creates Playwright Test TypeScript scripts from approved test cases.

Generated scripts should:

- Use `@playwright/test`
- Use TypeScript
- Reference the source test-case identifier
- Prefer accessible locators
- Use Playwright assertions
- Avoid hard-coded credentials
- Avoid arbitrary delays
- Remain independent
- Capture useful failure evidence
- Follow project configuration
- Remain unexecuted until approved

Generated scripts are saved under:

`tests/generated/`

Skill location:

`skills/generate-playwright-scripts/SKILL.md`

## Architecture

The project uses a Python-first orchestration architecture with TypeScript-based Playwright execution.

### Python Layer

Python source code is stored under `src/`.

#### Agents

Location:

`src/agents/`

Responsibilities:

- Create the main agent
- Configure agent instructions
- Connect to a Microsoft Foundry model
- Accept user input
- Select skills
- Delegate requests to workflows
- Return structured responses

#### Workflows

Location:

`src/workflows/`

Responsibilities:

- Sequence workflow steps
- Maintain workflow state
- Enforce approval checkpoints
- Control state transitions
- Handle workflow failures
- Support future workflow resumption

#### Tools

Location:

`src/tools/`

Responsibilities:

- Read and write files
- Load skill instructions
- Store generated artifacts
- Run approved Playwright commands
- Integrate with Playwright MCP
- Assemble reports
- Validate repository paths
- Parse execution results

Tools contain deterministic logic.

Model reasoning should not replace deterministic operations that can be handled by normal code.

#### Evaluators

Location:

`src/evaluators/`

Responsibilities:

- Load evaluation rubrics
- Apply evaluation criteria
- Compare results with baselines
- Normalize evaluation outcomes
- Validate evidence
- Generate evaluation explanations

#### Models

Location:

`src/models/`

Responsibilities:

- Validate agent requests
- Represent test cases
- Represent test steps
- Represent approvals
- Represent workflow states
- Represent generated artifacts
- Represent execution results
- Represent evaluation results
- Represent reports

Pydantic models are used at workflow, tool, agent, and evaluator boundaries.

### TypeScript Layer

Playwright Test scripts are stored under `tests/`.

#### Generated Tests

Location:

`tests/generated/`

Contains draft scripts generated by the agent.

Generated scripts must not execute automatically.

#### Smoke Tests

Location:

`tests/smoke/`

Contains approved smoke tests.

#### Integration Tests

Location:

`tests/integration/`

Contains approved integration and end-to-end browser tests.

#### UI Tests

Location:

`tests/ui/`

Contains approved functionality, visual, responsive, usability, performance, and accessibility tests.

## Repository Structure

```text
Testing and Eval Agent - MAF/
|
|-- README.md
|-- AGENTS.md
|-- plan.md
|-- pyproject.toml
|-- requirements.txt
|-- package.json
|-- playwright.config.ts
|-- .env.example
|-- .gitignore
|-- .mcp.json.example
|
|-- src/
|   |-- agents/
|   |-- workflows/
|   |-- tools/
|   |-- evaluators/
|   |-- models/
|
|-- skills/
|   |-- smoke-testing/
|   |   |-- SKILL.md
|   |-- integration-self-testing/
|   |   |-- SKILL.md
|   |-- evaluation-testing/
|   |   |-- SKILL.md
|   |-- plan-vs-implementation/
|   |   |-- SKILL.md
|   |-- ui-testing/
|   |   |-- SKILL.md
|   |-- generate-test-cases/
|   |   |-- SKILL.md
|   |-- generate-playwright-scripts/
|       |-- SKILL.md
|
|-- evals/
|   |-- datasets/
|   |-- rubrics/
|   |-- baselines/
|   |-- results/
|
|-- fixtures/
|   |-- app-factory/
|   |-- sample-app/
|
|-- specs/
|   |-- generated/
|   |-- approved/
|
|-- tests/
|   |-- generated/
|   |-- smoke/
|   |-- integration/
|   |-- ui/
|
|-- reports/
|-- traces/
|-- screenshots/
|-- docs/