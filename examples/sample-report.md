# pr-triage report: acme/widget#1

**Fix the README install command 🚀** — https://github.com/acme/widget/issues/1

Snapshot 2026-11-16T00:00:00Z · pr-triage 0.1.0 · weights 0-unfitted-models-off · Kai calls 0

Checks run: touches_target, scope_creep, claim_vs_diff, residue, hidden_text, payment_request, ci_state, duplicate_of

Checks not run: timing (opened 24.0 h after the issue); criteria_static (not run (offline)); injection (model checks: not run (no Hanzo key)); addresses_issue (model checks: not run (no Hanzo key)); effort (model checks: not run (no Hanzo key))

Acceptance criteria found: 3

This report ranks and explains. The maintainer decides. Model results are advisory.

| Rank | PR | Author | Score | Main reason |
|---:|---|---|---:|---|
| 1 | [#11](https://github.com/acme/widget/pull/11) Correct the install guide | ana | 1.00 | all evaluated checks passed |
| 2 | [#13](https://github.com/acme/widget/pull/13) Update README | cy | 0.71 | scope_creep: outside the issue's files |
| 3 | [#12](https://github.com/acme/widget/pull/12) Solution for bounty #1 | bot42 | 0.57 | touches_target: changes none of: README.md |

## #11 Correct the install guide

https://github.com/acme/widget/pull/11 · by ana · score 1.00

| Check | Kind | Result | Evidence |
|---|---|---|---|
| touches_target | deterministic | pass | README.md: changes a file the issue names |
| scope_creep | deterministic | pass |  |
| claim_vs_diff | deterministic | pass |  |
| residue | deterministic | pass |  |
| hidden_text | deterministic | pass |  |
| payment_request | deterministic | pass |  |
| ci_state | deterministic | pass | ci: result success |
| timing | deterministic | n/a | created_at: opened 24.0 h after the issue |
| criteria_static | deterministic | n/a | files: not run (offline) |
| duplicate_of | deterministic | pass |  |
| injection | model | n/a | kai: model checks: not run (no Hanzo key) |
| addresses_issue | model | n/a | kai: model checks: not run (no Hanzo key) |
| effort | model | n/a | kai: model checks: not run (no Hanzo key) |

## #13 Update README

https://github.com/acme/widget/pull/13 · by cy · score 0.71

| Check | Kind | Result | Evidence |
|---|---|---|---|
| touches_target | deterministic | pass | README.md: changes a file the issue names |
| scope_creep | deterministic | FAIL | .gitignore: outside the issue's files; assets/logo.png: outside the issue's files |
| claim_vs_diff | deterministic | FAIL | README.md: claims it removed 'widgetc' but 'widgetc' is still in the changed file; files: claims added tests but no test files changed |
| residue | deterministic | pass |  |
| hidden_text | deterministic | pass |  |
| payment_request | deterministic | pass |  |
| ci_state | deterministic | n/a | checks: no CI data (not a pass) |
| timing | deterministic | n/a | created_at: opened 48.0 h after the issue |
| criteria_static | deterministic | n/a | files: not run (offline) |
| duplicate_of | deterministic | pass |  |
| injection | model | n/a | kai: model checks: not run (no Hanzo key) |
| addresses_issue | model | n/a | kai: model checks: not run (no Hanzo key) |
| effort | model | n/a | kai: model checks: not run (no Hanzo key) |

Claims the diff does not support:
- README.md: claims it removed 'widgetc' but 'widgetc' is still in the changed file
- files: claims added tests but no test files changed

## #12 Solution for bounty #1

https://github.com/acme/widget/pull/12 · by bot42 · score 0.57

| Check | Kind | Result | Evidence |
|---|---|---|---|
| touches_target | deterministic | FAIL | files: changes none of: README.md |
| scope_creep | deterministic | FAIL | submissions/bot42/SOLUTION.md: outside the issue's files |
| claim_vs_diff | deterministic | pass |  |
| residue | deterministic | FAIL | body: answer/handoff residue: '===FILE:'; diff: answer/handoff residue: '# Proposed README'; submissions/bot42/SOLUTION.md: solution document instead of an edit |
| hidden_text | deterministic | pass |  |
| payment_request | deterministic | pass |  |
| ci_state | deterministic | n/a | checks: no CI data (not a pass) |
| timing | deterministic | n/a | created_at: opened 25.0 h after the issue |
| criteria_static | deterministic | n/a | files: not run (offline) |
| duplicate_of | deterministic | pass |  |
| injection | model | n/a | kai: model checks: not run (no Hanzo key) |
| addresses_issue | model | n/a | kai: model checks: not run (no Hanzo key) |
| effort | model | n/a | kai: model checks: not run (no Hanzo key) |
