"""Render a ranked reviewer report as Markdown and JSON."""
from __future__ import annotations

import dataclasses

from .criteria import extract_criteria
from .model import CheckResult, Issue, PR


def _rank(prs: list[PR], scores: dict[str, float]) -> list[PR]:
    return sorted(prs, key=lambda p: (-scores[p.ref], p.created_at, p.ref))


def _reason(results: list[CheckResult], weights: dict) -> str:
    failed = sorted((r for r in results if r.passed is False), key=lambda r: -float(weights.get(r.id, 0)))
    if not failed:
        return "all evaluated checks passed"
    r = failed[0]
    return f"{r.id}: {r.evidence[0].detail}" if r.evidence else r.id


def _esc(s: str) -> str:
    return (s or "").replace("|", "/").replace("\n", " ")


def check_coverage(results: dict[str, list[CheckResult]]) -> tuple[list[str], dict[str, str]]:
    ids = [r.id for r in next(iter(results.values()), [])]
    run, not_run = [], {}
    for cid in ids:
        rows = [r for rs in results.values() for r in rs if r.id == cid]
        if any(r.passed is not None for r in rows):
            run.append(cid)
        else:
            first = next((e.detail for r in rows for e in r.evidence), "not evaluated")
            not_run[cid] = first
    return run, not_run


def render(issue: Issue, prs: list[PR], results: dict[str, list[CheckResult]], scores: dict[str, float], meta: dict) -> tuple[str, dict]:
    weights = meta.get("weights", {})
    ranked = _rank(prs, scores)
    run, not_run = check_coverage(results)
    meta = {**{k: v for k, v in meta.items() if k != "weights"}, "checks_run": run, "checks_not_run": not_run}
    crits = extract_criteria(issue)
    md = [f"# pr-triage report: {issue.ref}", "", f"**{issue.title}** — {issue.url}", "",
          f"Snapshot {meta.get('snapshot_time', '?')} · pr-triage {meta.get('tool_version', '?')} · "
          f"weights {meta.get('weights_version', '?')} · Kai calls {meta.get('kai_calls', 0)}", "",
          "Checks run: " + (", ".join(run) or "none"), ""]
    if not_run:
        md += ["Checks not run: " + "; ".join(f"{k} ({v})" for k, v in not_run.items()), ""]
    free = [c.text for c in crits if c.kind == "free_text"]
    md += ([f"Acceptance criteria found: {len(crits)}"]
           + (["Free-text criteria for the reviewer: " + "; ".join(_esc(x) for x in free)] if free else []) if crits else
           ["No acceptance criteria found in the issue; no PR is penalised for this."]) + [""]
    md += ["This report ranks and explains. The maintainer decides. Model results are advisory.", "",
           "| Rank | PR | Author | Score | Main reason |", "|---:|---|---|---:|---|"]
    label = lambda p: f"#{p.number}" if p.repo == issue.repo else p.ref
    for i, p in enumerate(ranked, 1):
        md.append(f"| {i} | [{label(p)}]({p.url}) {_esc(p.title)[:60]} | {p.author} | {scores[p.ref]:.2f} | {_esc(_reason(results[p.ref], weights))[:120]} |")
    for p in ranked:
        rs = results[p.ref]
        md += ["", f"## {label(p)} {_esc(p.title)}", "", f"{p.url} · by {p.author} · score {scores[p.ref]:.2f}", "",
               "| Check | Kind | Result | Evidence |", "|---|---|---|---|"]
        for r in rs:
            res = "n/a" if r.passed is None else ("pass" if r.passed else "FAIL")
            ev = "; ".join(f"{e.where}: {e.detail}" for e in r.evidence)[:300]
            md.append(f"| {r.id} | {r.kind} | {res} | {_esc(ev)} |")
        unsupported = [e for r in rs if r.id == "claim_vs_diff" and r.passed is False for e in r.evidence]
        if unsupported:
            md += ["", "Claims the diff does not support:"] + [f"- {e.where}: {e.detail}" for e in unsupported]
    js = {
        "issue": {"ref": issue.ref, "url": issue.url, "title": issue.title, "criteria": [dataclasses.asdict(c) for c in crits]},
        "meta": meta,
        "ranking": [{"rank": i, "ref": p.ref, "number": p.number, "url": p.url, "author": p.author, "score": scores[p.ref],
                     "reason": _reason(results[p.ref], weights)} for i, p in enumerate(ranked, 1)],
        "checks": {ref: [dataclasses.asdict(r) for r in rs] for ref, rs in results.items()},
    }
    return "\n".join(md) + "\n", js
