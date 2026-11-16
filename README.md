# pr-triage

When one issue attracts many competing pull requests, a maintainer has to read every one to find
the one that does the job. `pr-triage` reads the issue and every PR linked to it, checks each PR
against what the issue asks for, and writes a ranked reviewer report with the evidence behind
every judgement. It never runs PR code, and the maintainer makes the decision.

It comes with a calibration harness and a reproducible study on 24 real bounty issues, so its
claims rest on measurements.

## What it checks

| Check | Kind | What it looks for |
|---|---|---|
| `touches_target` | deterministic | changes the files the issue names |
| `scope_creep` | deterministic | changes files the issue did not ask for (`.gitignore` tool rules, lockfiles, workflows) |
| `claim_vs_diff` | deterministic | description claims the diff does not support ("removed X" while X remains, "added tests" with none) |
| `criteria_static` | deterministic | the issue's checkable acceptance criteria on the post-PR file text (contains / must not contain / links) |
| `duplicate_of` | deterministic | identical changed lines to an earlier PR (the later one is the copy) |
| `residue`, `hidden_text`, `payment_request` | deterministic | answer-handoff residue and solution documents instead of edits; HTML comments and invisible Unicode; payout wording on points-only bounties |
| `ci_state` | deterministic | check-run results ("no data" is never a pass) |
| `injection`, `addresses_issue`, `effort` | model (Hanzo Kai, optional) | advisory only; **weight 0** until they pass their own validation (see the study) |

A check that cannot be evaluated (no patch for a large file, deleted fork, no criteria in the
issue) returns "not evaluated" and never counts against a PR.

## Quick start

```bash
pip install git+https://github.com/dboles99/pr-triage
export GH_TOKEN=...            # optional; raises GitHub's rate limit
pr-triage review OWNER/REPO#123             # writes out/OWNER_REPO_123/report.md and report.json
pr-triage review OWNER/REPO#123 --no-kai    # skip the optional Kai checks
```

Python 3.10+, standard library only. A [sample report](examples/sample-report.md) is built from
the synthetic test fixture.

### As a GitHub Action

Copy [examples/triage.yml](examples/triage.yml) into `.github/workflows/`. A user with write access
comments exactly `/triage` on an issue. The Action reads metadata and diffs through the API, posts
or updates a single summary comment, and uploads the full report as an artifact. It does not check
out PR code.

## Study: does it rank the PR a maintainer merged first?

Data: every Hanzo bounty issue (orgs hanzoai, hanzo-go, hanzo-js, hanzo-apps) with at least two
linked PRs. That is 27 issues and 167 PRs, collected 2026-11-16, and 24 of the issues had exactly
one PR merged. One issue (hanzo-go/lz4#1) is excluded because the author's own PR competes on it.

| Ordering | Top-1 | Mean reciprocal rank |
|---|---:|---:|
| **pr-triage** (default weights, model checks off) | **0.26** | **0.51** (95% CI 0.44–0.58) |
| random order (exact expectation) | 0.20 | 0.44 |
| most reactions first | 0.20 | 0.44 |
| earliest PR first | 0.13 | 0.40 |
| smallest diff first | 0.08 | 0.33 |
| ranking by the manual labels themselves | 0.34 | 0.58 |

Ties are broken uniformly at random for every ordering alike. Weights fitted leave-one-issue-out
reach an MRR of 0.55.

What the study shows:

- **pr-triage beats every simple baseline, by a small margin.** The lower end of its confidence
  interval only just clears random.
- **Merge choice is a weak target for a quality ranker.** Even the manual labels reach only MRR
  0.58. 23 of the 24 merged PRs addressed the issue, but so did 83 of the 122 that were not merged.
  When several PRs are acceptable, maintainers choose on things no check here measures.
- **The tool works better as a filter.** When `touches_target` says a PR misses the files the
  issue names, it agrees with the manual labels 94% of the time.
- **The Kai checks did not earn a place.** The injection screen missed its own positive control,
  and "addresses the issue" and "effort" scored AUC 0.52 and 0.54 against the labels. So they carry
  no weight.
- **Some checks never fired on this data** (`residue`, `ci_state` and others), so they cannot help
  here.

The method, per-check numbers, every miss and the limits are in
[study/results/REPORT.md](study/results/REPORT.md). The published data are references, hashes and
derived values only; no contributor text is included. Labels were made blind by a separate
assistant session from [study/RUBRIC.md](study/RUBRIC.md), and the author spot-checked 20 at random,
agreeing on 59 of 60.

Rerun the study:

```bash
pr-triage study build --raw <private-dir>       # collects snapshots (needs GH_TOKEN)
pr-triage study run --raw <private-dir> --labels study/labels.csv [--kai]
pr-triage study run --labels study/labels.csv  # re-fetches from GitHub and reports drift
```

## Limits

- The data are from one organisation's bounty program, with a small number of issues.
- Maintainers' merge decisions are the ground truth, and they can have reasons no check sees.
- The labels come from an assistant and were spot-checked by one person.
- The model checks are opinions.
- The heuristics (claims, residue, payment wording) are English-centric and conservative.

## Development

```bash
python -m unittest discover -s tests -v
```

MIT licence. Author: Daniel Boles.
