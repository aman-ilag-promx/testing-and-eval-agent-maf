# Testing and Evaluation Agent Plan

## Objective

Provide one practical, approval-gated testing path for GitHub repositories and browser-reachable applications. A conversation collects the target and test level; optional MCP observations inform test design; Playwright Test produces the only pass/fail result.

## Supported Test Levels

- **Smoke**: approved scripts in `tests/smoke/` validate availability and critical paths.
- **Integration**: approved scripts in `tests/integration/` validate connected behavior.
- **UI**: approved scripts in `tests/ui/` validate functional, accessibility, responsive, visual, performance, and usability scenarios where appropriate.
- **Evaluation**: rubric-based assessment consumes deterministic execution evidence and stops for review.
- **Plan comparison**: compares approved requirements and implementation evidence; it never edits the tested application.

## Minimal Lifecycle

```text
Natural-language request
  -> optional read-only GitHub or Playwright MCP observation
  -> draft test cases in specs/generated/
  -> Checkpoint A: human approval
  -> draft Playwright script in tests/generated/
  -> Checkpoint B: human approval
  -> promoted approved script in tests/smoke/, tests/integration/, or tests/ui/
  -> separately approved deterministic Playwright Test execution
  -> optional evaluation
  -> Checkpoint C: human review of evaluation
```

## GitHub MCP

The agent uses GitHub's hosted read-only MCP endpoint directly:

```text
https://api.githubcopilot.com/mcp/readonly
```

- Docker is not required for the hosted endpoint.
- The Python agent authenticates with an environment-only, fine-grained GitHub personal access token. OAuth handled by VS Code cannot be reused by this standalone CLI process.
- The token must be limited to intended repositories with read-only Metadata and Contents permissions; add read-only Issues and Pull requests only when those observations are needed.
- The agent permits only repository metadata, file contents, commits, issues, pull requests, and code search. MCP observations are never test results.
- The adapter, remote `/readonly` endpoint, and token permissions jointly prevent repository writes.

## Playwright MCP and Playwright Test

- **Playwright MCP** is optional browser exploration for any browser-reachable target. It may discover page structure, locators, accessibility information, and screenshots. Its observations never prove a test outcome.
- **Playwright Test** is the deterministic execution layer for every supported target with an HTTP or HTTPS UI. It runs only approved scripts and records execution output, traces, and screenshots.
- GitHub repository inspection alone does not execute a repository's code. For browser tests, the request must provide a permitted non-production `base_url`.

## Safety and Approval Rules

- Never run a draft script from `tests/generated/`.
- Never report a pass/fail result without Playwright Test execution evidence.
- `ALLOW_LIVE_TEST_EXECUTION` remains `false` by default.
- Production and destructive testing are blocked by default.
- GitHub MCP must remain read-only; Azure DevOps and App Factory integration are out of scope.
- No credentials may be persisted in test artifacts, reports, conversations, or configuration output.

## Definition of Done

1. A GitHub URL can gather disclosed read-only observations through the hosted endpoint when a valid token is configured.
2. A web application URL can generate, approve, and run smoke, integration, or UI scripts through Playwright Test.
3. Every level remains blocked at the required approval checkpoint.
4. Tests, linting, and type checks cover the changed behavior.
5. Missing credentials, unavailable MCP services, unapproved scripts, and unavailable target URLs produce structured failures without false test claims.