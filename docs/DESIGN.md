# pr-triage: design

Date: 2026-11-16. Owner: Daniel Boles (GitHub dboles99). Status: draft for owner approval.
Project A of piece 5 in `docs/HANZO_ADOPTION_PLAN.md` (Project B, the hanzoai/mcp#35 research
bounty, follows later and is not designed here).

## 1. Intent

When a bounty issue attracts many pull requests, maintainers must read every one to find the one
that actually does the job. Hanzo's own program shows the scale: of 77 bounty issues, 28 drew two
or more linked PRs (176 PRs in total; hanzoai/agents#8 alone drew 13).
Many are low effort: no README change on a README issue, answer-document residue, claims the diff
does not support, unrelated file changes, payout requests.

`pr-triage` is a tool a maintainer runs on one issue. It collects the issue and its competing PRs,
checks each PR against the issue, and produces a ranked reviewer report with the evidence for every
judgement. A built-in calibration harness measures every rule and every model question against
real outcomes, so the tool's claims are backed by numbers.

It must serve two audiences at once:
- **Employers and clients:** a public repo under dboles99 that shows research method (a measured,
  reproducible evaluation with honest limits) and engineering (clean, tested, documented code).
- **Hanzo maintainers:** something they could adopt for their bounty flow, offered through a short
  proposal issue that links to the repo and study (posted only after the owner approves the text).

## 2. Goals, non-goals, anti-goals

Goals
1. CLI `pr-triage review OWNER/REPO#N` writes `report.md` and `report.json` for any public repo.
2. Each PR gets per-check results with evidence (file, line, quoted span or metric), a combined
   score, and a rank. The report says which checks are deterministic and which are model opinions.
3. A calibration harness (`pr_triage.calibrate`) that evaluates any check or model question against
   a labelled set: accuracy/precision/recall, Brier score, reliability (calibration) table, and a
   threshold chooser with stated trade-offs. Reusable outside this project (idea 2).
4. A study (`study/`) on Hanzo's closed bounty issues, reproducible from a pinned snapshot with one
   command, written up as `study/REPORT.md`.
5. A thin GitHub Action that runs the review when a maintainer comments `/triage` on an issue.

Non-goals
- Auto-merging, auto-closing, labelling or commenting on contributors' PRs.
- Deciding the bounty winner. The tool ranks and explains; the maintainer decides.
- An AI-authorship detector. Disclosures and residue are reported as observable text, never as a
  claim about who or what wrote a PR (the lab's rule D007).
- Hanzo-native cloud agents (their tool calls do not work today, hanzoai/cloud#12).

Anti-goals (would make it a failure even if it works)
- Running any PR's code. Analysis reads metadata and diffs only.
- Publishing contributors' full PR bodies or comments in the repo, or ranking people rather than
  PRs. The study publishes URLs, hashes and derived features, not copied text.
- Unmeasured claims: no "accuracy" sentence without the study number behind it.
- Leaking credentials: the Kai key never appears in config, logs, reports or CI output.

## 3. Constraints

- Python 3.10+, standard library only for the core (as in the lab). Optional extras allowed for the
  study's charts (matplotlib) behind an extra; the core must run without them.
- GitHub data via the REST API with an optional token (`GH_TOKEN`/`GITHUB_TOKEN`), or `gh`. Must work
  unauthenticated for small issues (60 req/h) and report rate limits clearly.
- Kai is optional. Without a Hanzo key every deterministic check still runs and the report says
  "model checks: not run". With a key, Kai questions run and are cached by input hash.
- Free-plan budget: 50 Kai decisions/day. The study must state its Kai call count and fit the budget
  (cache, batch questions per PR, `--max-kai-calls`).
- All GitHub text is untrusted input; it is analysed, never followed.
- Commits: Daniel Boles only, no co-author or tool attribution (repo ships the commit-msg hook).
- No external write by the tool except, in the Action, one comment on the issue when a maintainer
  triggers it. Everything public from this project (repo creation, push, Hanzo proposal) waits for
  the owner's approval of the exact content.

## 4. Approaches considered

| Approach | Trade-off | Decision |
|---|---|---|
| Extract from the task lab (Python stdlib, CLI + thin Action) | Reuses tested evidence collection, rule scanner, DocGuard-style checks and the Kai client; fastest credible result | **Chosen by the owner** |
| Fresh TypeScript GitHub Action | Native to Actions and Hanzo's JS ecosystem; nothing reused, slower | Rejected |
| Python engine + separate TypeScript Action | Most complete; two toolchains, most work | Rejected for v1 |

Name chosen by the owner: `pr-triage` (repo `dboles99/pr-triage`, public when the owner approves).

## 5. Design

### 5.1 Pipeline

`collect -> normalise -> check -> score -> report`, each stage a module with JSON in and out, so the
study can replay any stage from a snapshot.

1. **collect** (`collect.py`): issue, comments, timeline cross-references, and for each linked PR:
   metadata, files with patches, commits, reviews, review comments, check runs/statuses, reactions.
   Saved as one snapshot JSON with collection time and API response counts (lab `refresh` logic).
2. **normalise** (`model.py`): dataclasses `Issue`, `PR`, `FileChange`, plus `criteria` extracted
   from the issue (section 5.3).
3. **check** (`checks/`): each check is a function `check(issue, pr) -> CheckResult(id, kind,
   value, passed|None, evidence[])` with `kind` = `deterministic` or `model`.
4. **score** (`score.py`): weighted combination with weights loaded from a versioned file; the
   default weights are the ones the study fits (section 6), not hand-tuned guesses.
5. **report** (`report.py`): Markdown and JSON. Every number links to its evidence.

### 5.2 Checks (v1)

Deterministic
- `touches_target`: changes the files the issue names or implies (e.g. README.md for a README issue).
- `scope_creep`: changed files outside the issue's scope (unrelated config, `.gitignore`, lockfiles).
- `claim_vs_diff`: claims in the PR body ("removed X", "added tests", "fixes #N") compared with the
  diff (X still present? any test files changed?).
- `criteria_static`: issue acceptance criteria that can be checked statically on the post-PR text of
  changed files (string present/absent, link targets), generalising DocGuard.
- `duplicate_of`: near-identical change sets between PRs (lab similarity, exact-lines flag).
- `residue`: answer/handoff residue, solution documents instead of edits (lab rules).
- `hidden_text`: HTML comments, invisible Unicode (lab rules).
- `payment_request`: payout wording that conflicts with the issue's reward terms.
- `ci_state`: check-run/status outcomes, with "no data" kept distinct from "pass".
- `timing`: opened before/after the issue's claim comments, time since issue (context, not quality).

Model (Kai, optional)
- `injection`: Kai planted-instruction screen on PR body and comments (threshold 0.9057, as in the
  lab). Flag means "show the maintainer", never "reject".
- `addresses_issue`: noul with both sides described: "The change described and shown addresses the
  issue's stated request."
- `effort`: score levels for low-effort vs substantive, with both ends described.
Model questions are written to be measured: each ships with positive and negative controls and is
kept only if the study shows it separates outcomes (the lab's triage `fit` question did not).

### 5.3 Acceptance criteria extraction

Deterministic first: parse `## Acceptance criteria` / checklist items / "What to do" bullets. Each
criterion becomes a typed item when a pattern applies (file must contain/not contain a string, link
must return 200, command must exist) and stays free text otherwise. Free-text criteria are listed in
the report for the human and, when Kai is available, checked with one noul per criterion. Link
checks are off by default (`--links`) and never send credentials.

### 5.4 Report

Per issue: a ranked table (rank, PR, author, score, one-line reason), then one section per PR with
each check's result and evidence, a "claims the diff does not support" list, duplicates, and model
flags. Header states snapshot time, checks run/not run, Kai calls used, and the tool version. JSON
mirrors the same structure for the Action and the study.

### 5.5 GitHub Action

`action.yml` (composite) running `python -m pr_triage review` on `issue_comment` events whose body is
exactly `/triage` from a user with write access. Posts or updates one comment with the summary table
and a link to the full report artifact. `HANZO_API_KEY` is an optional repository secret. No other
events, no PR code checkout (metadata and diffs via the API only).

### 5.6 Repository layout

```
pr-triage/
  pr_triage/        collect, model, checks/, score, report, calibrate, kai, cli
  tests/            unit tests per check with fixtures from real (public) PR metadata
  study/            snapshot manifest, labels, run_study.py, REPORT.md, figures/
  action.yml
  README.md         what it does, quick start, a sample report, honest limits
  LICENSE           MIT
  .githooks/commit-msg
```

## 6. Evaluation (the study)

Data (recounted 2026-11-16 with UTF-8-safe timeline reads): 77 Hanzo bounty issues; **28 with two
or more linked PRs, 176 PRs**. Outcomes: **23 issues with exactly one merged linked PR** (the primary
evaluation set), 3 with several merged PRs (hanzoai/ai#133, #135, #138 share umbrella PRs #147/#149/
#151; reported separately), 2 open (hanzo-go/lz4#1, hanzoai/vfs#29). Snapshot pinned with collection
time and hashes; the study re-runs from the snapshot.

**Definitions (builder's call, recorded):** a PR is *linked* to an issue when the issue timeline has a
`cross-referenced` event whose source is a pull request, any state, any repo; the collector stores the
method and raw counts. An issue's outcome is *accepted* when a linked PR has `merged_at`; two issues
were also closed by a commit, both with a merged PR, so no extra category is needed.

**Excluded (owner decision):** hanzo-go/lz4#1, where the owner's PR #22 competes. It is left out of
the study, metrics, fixtures and sample report, and the owner labels no issue he competed on. Disclosed
in REPORT.md.

Ground truth
1. **Maintainer outcome** (primary, free of our bias): for each closed issue, which PR was merged.
2. **Manual labels** (secondary, owner decision): the assistant labels every PR from a written rubric
   ("addresses the issue", "scope creep", "claims unsupported by diff") **before** seeing any tool
   scores; the owner spot-checks a random 20 in one sitting; agreement is reported, and labels are
   marked assistant-made with date. Used only to measure individual checks, kept separate from outcome.

Publishing and reproducibility (builder's call, recorded): the public repo carries URLs, content
hashes and derived features only. The raw snapshot stays private in the lab. `study/run_study.py`
either replays from the private snapshot or re-fetches from GitHub and reports any drift (edited or
deleted PRs) against the published hashes.

Kai budget (owner decision): up to **$1 of paid credits** for the study, hard stop at $1, one
multi-question decision per PR plus controls (~200 decisions), cached by input hash so reruns cost
nothing.

Metrics
- Ranking: top-1 hit rate (does rank 1 equal the merged PR), mean reciprocal rank, on issues with a
  merged PR; for "none accepted" issues, whether every PR scores below the acceptance threshold.
- Per check: precision/recall against manual labels; per model question: Brier score, reliability
  table, AUC where meaningful.
- Baselines: random order, earliest PR first, smallest diff first, most reactions first.
- Validation: leave-one-issue-out when fitting score weights (19 issues is small); report
  confidence intervals and say plainly that the sample is small and from one organisation.

Deliverable: `study/REPORT.md` with method, data, results table, baselines, calibration figures,
error analysis of misses, and limits (one org, small n, maintainer behaviour as ground truth).

## 7. Decided so far

- Project A covers ideas 1 and 2; Project B (mcp#35) follows.
- Built by extracting from the lab; Python stdlib core; CLI plus thin Action.
- Repo `dboles99/pr-triage` created **private** now for Action testing; made public, and the Hanzo
  proposal issue posted, only after the owner approves the content.
- Audience: employers/clients and Hanzo maintainers.
- Standalone copy built from the lab (builder's call): the lab is not refactored to import it now.
  Note: DocGuard needs a full checkout; `criteria_static` must work on post-PR file text from the API.

## 8. Left to the builder

- Exact module boundaries and dataclass fields; CLI flag names beyond `review`, `calibrate`, `study`.
- Check weights (fitted by the study), report styling, fixture selection.
- How to page and cache GitHub calls; retry policy; which optional chart dependency to use.
- Wording of model questions, subject to the controls-and-measurement rule above.
