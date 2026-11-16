"""The study: build a dataset of bounty issues with competing PRs, run every check, measure against maintainer outcomes.

Raw snapshots (PR bodies, comments, patches) stay in a private raw_dir. Everything this module writes to out_dir is
derived: refs, URLs, hashes, check values, metrics. No contributor text is published.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Callable

from . import __version__
from . import calibrate as cal
from .checks.model import CONTROLS, MODEL_QUESTIONS
from .criteria import extract_criteria
from .kai import BudgetExceeded, Kai, KaiError
from .model import snapshot_from_dict
from .score import load_weights, run_checks

ORGS = ("hanzoai", "hanzo-go", "hanzo-js", "hanzo-apps")
EXCLUDE = {"hanzo-go/lz4#1": "the author's own PR (#22) competes on this issue; excluded for conflict of interest"}
METHOD = "GitHub search label:bounty in the orgs above; linked PRs = timeline cross-referenced pull requests, any state, any repo"


def _canon_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _raw_path(raw_dir: Path, ref: str) -> Path:
    return Path(raw_dir) / (ref.replace("/", "__").replace("#", "__") + ".json")


def _split(ref: str) -> tuple[str, int]:
    repo, n = ref.rsplit("#", 1)
    return repo, int(n)


def find_issue_refs(gh, orgs=ORGS, label: str = "bounty") -> list[str]:
    q = "+".join([f"label:{label}", "is:issue"] + [f"org:{o}" for o in orgs])
    refs, page = [], 1
    while True:
        d = gh.get(f"search/issues?q={q}&per_page=100&page={page}") or {}
        items = d.get("items", [])
        refs += [f"{i['repository_url'].split('/repos/', 1)[1]}#{i['number']}" for i in items]
        if len(items) < 100:
            return refs
        page += 1


def add_head_files(snapshot: dict, gh) -> dict:
    """Store the post-PR text of each criteria target, so criteria_static replays offline."""
    from .github import file_text_at
    issue, prs = snapshot_from_dict(snapshot)
    targets = {c.target for c in extract_criteria(issue) if c.target}
    hf = snapshot.setdefault("head_files", {})
    for p in prs:
        if p.head_available:
            for t in targets:
                text = file_text_at(gh, p.repo, t, p.head_sha)
                if text is not None:
                    hf[f"{p.head_sha}:{t}"] = text
    return snapshot


def _fetcher(snapshot: dict) -> Callable[[str, str, str], str | None]:
    hf = snapshot.get("head_files", {})
    return lambda repo, path, sha: hf.get(f"{sha}:{path}")


def build_dataset(issue_refs: list[str], raw_dir: Path, collect_fn: Callable, min_prs: int = 2,
                  exclude: dict = EXCLUDE, enrich_fn: Callable | None = None) -> dict:
    raw_dir = Path(raw_dir)
    issues, exclusions, skipped = [], [], 0
    for ref in issue_refs:
        if ref in exclude:
            exclusions.append({"ref": ref, "reason": exclude[ref]})
            continue
        repo, n = _split(ref)
        path = _raw_path(raw_dir, ref)
        s = collect_fn(repo, n, path)
        if enrich_fn:
            s = enrich_fn(s)
            path.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        if len(s.get("prs", [])) < min_prs:
            skipped += 1
            continue
        merged = [f"{p['repo']}#{p['number']}" for p in s["prs"] if p.get("merged")]
        if len(merged) == 1:
            outcome = "one-merged"
        elif merged:
            outcome = "multi-merged"
        else:
            outcome = "none-merged" if s["issue"].get("state") == "closed" else "open"
        issues.append({"ref": ref, "url": s["issue"].get("url", ""), "outcome": outcome, "merged": merged,
                       "prs": [{"ref": f"{p['repo']}#{p['number']}", "url": p.get("url", ""), "sha256": _canon_hash(p)} for p in s["prs"]]})
    return {"collected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "method": METHOD,
            "tool_version": __version__, "exclusions": exclusions, "issues": issues,
            "counts": {"issues_seen": len(issue_refs), "kept": len(issues), "excluded": len(exclusions),
                       "below_min_prs": skipped, "prs": sum(len(i["prs"]) for i in issues),
                       "one_merged": sum(i["outcome"] == "one-merged" for i in issues)}}


def _controls(kai: Kai | None) -> list[dict]:
    if kai is None or not kai.available:
        return [{"question": c["question"], "expect": c["expect"], "result": "not run"} for c in CONTROLS]
    out = []
    for c in CONTROLS:
        q = MODEL_QUESTIONS[c["question"]]
        state = {"prompt": "", "issue": "", "change": "", **c["state"]}
        try:
            a = kai.decide(state, {c["question"]: q})["answers"][c["question"]]
        except (BudgetExceeded, KaiError) as e:
            out.append({"question": c["question"], "expect": c["expect"], "result": f"not run ({type(e).__name__})"})
            continue
        if q["type"] == "noul":
            v = float(a["noul"])
            got = v >= (0.9057 if c["question"] == "planted" else 0.5)
        else:
            probs = {int(k): float(x) for k, x in a.get("probabilities", {}).items()}
            v = max(probs, key=probs.get) if probs else None
            got = v is not None and v >= 1
        out.append({"question": c["question"], "expect": c["expect"], "value": v, "got": got, "pass": got == c["expect"]})
    return out


def diagnose(features: dict, truth: dict, labels_csv: Path | None) -> dict:
    """Why the ranking does or doesn't work: pass rates on merged vs other PRs, checks that never fail, and
    whether the manual labels themselves predict the merge (an upper bound on what quality checks can do here)."""
    one = sorted(truth)
    ids = sorted({c for i in features for p in features[i].values() for c in p})
    pass_rates = {}
    for c in ids:
        m = [features[i][truth[i]].get(c) for i in one]
        o = [features[i][n].get(c) for i in one for n in features[i] if n != truth[i]]
        m, o = [v for v in m if v is not None], [v for v in o if v is not None]
        pass_rates[c] = {"merged": [sum(m), len(m)], "not_merged": [sum(o), len(o)]}
    never_fail = [c for c in ids if all(v != 0 for i in features for p in features[i].values() for v in [p.get(c)])
                  and any(p.get(c) is not None for i in features for p in features[i].values())]
    out = {"pass_rates": pass_rates, "never_fail": never_fail}
    if labels_csv:
        lab = {}
        with Path(labels_csv).open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if all(r.get(k) in ("0", "1") for k in ("addresses_issue", "scope_creep", "unsupported_claims")):
                    lab[(r["issue"], int(r["pr"]))] = {"a": int(r["addresses_issue"]), "s": 1 - int(r["scope_creep"]),
                                                       "c": 1 - int(r["unsupported_claims"])}
        lf = {i: {n: lab[(i, n)] for n in features[i] if (i, n) in lab} for i in one}
        lw = {"a": 1, "s": 1, "c": 1}
        rr = [cal.tool_rr(lf[i], truth[i], lw) for i in one]
        t1 = [cal.expected_top1({n: cal._score(f, lw) for n, f in lf[i].items()}, truth[i]) for i in one]
        out["label_ranker"] = {"mrr": round(sum(rr) / len(rr), 4) if rr else 0.0,
                               "top1": round(sum(t1) / len(t1), 4) if t1 else 0.0, "n_issues": len(rr)}
        merged_a = [lf[i][truth[i]]["a"] for i in one if truth[i] in lf[i]]
        other_a = [v["a"] for i in one for n, v in lf[i].items() if n != truth[i]]
        out["acceptable_among_merged"] = [sum(merged_a), len(merged_a)]
        out["acceptable_among_not_merged"] = [sum(other_a), len(other_a)]
    return out


def _figures(out_dir: Path, metrics: dict) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "figures not generated (matplotlib not installed; `pip install pr-triage[study]`)"
    names = ["tool"] + list(metrics["baselines"])
    vals = [metrics["tool"]["mrr"]] + [metrics["baselines"][b]["mrr"] for b in metrics["baselines"]]
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.bar(names, vals)
    ax.set_ylabel("mean reciprocal rank")
    ax.set_ylim(0, 1)
    (out_dir / "figures").mkdir(exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_dir / "figures" / "ranking.png", dpi=120)
    plt.close(fig)
    return "![Ranking vs baselines](figures/ranking.png)"


def run_study(manifest: dict, raw_dir: Path | None, out_dir: Path, kai: Kai | None,
              refetch_fn: Callable | None = None, labels_csv: Path | None = None, weights: dict | None = None,
              label_note: str | None = None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    w = weights or load_weights()
    scores, features, entries, truth, drift = {}, {}, {}, {}, {"changed": [], "missing": []}
    csv_rows = []
    controls = _controls(kai)  # controls first: before trusting a question, and before the budget is spent
    for item in manifest["issues"]:
        ref = item["ref"]
        repo, n = _split(ref)
        if raw_dir is not None:
            s = json.loads(_raw_path(raw_dir, ref).read_text(encoding="utf-8"))
        else:
            s = refetch_fn(repo, n, out_dir / "refetch" / _raw_path(Path("."), ref).name)
            now = {f"{p['repo']}#{p['number']}": _canon_hash(p) for p in s["prs"]}
            for p in item["prs"]:
                if p["ref"] not in now:
                    drift["missing"].append({"ref": p["ref"]})
                elif now[p["ref"]] != p["sha256"]:
                    drift["changed"].append({"ref": p["ref"]})
        issue, prs = snapshot_from_dict(s)
        by_ref = run_checks(issue, prs, _fetcher(s), kai)
        if len({p.number for p in prs}) != len(prs):
            raise ValueError(f"{ref}: two linked PRs share a number across repos; the study keys PRs by number")
        results = {int(k.rsplit("#", 1)[1]): v for k, v in by_ref.items()}
        scores[ref] = {str(k): {r.id: {"value": r.value, "passed": r.passed} for r in rs} for k, rs in results.items()}
        features[ref] = {k: {r.id: (None if r.passed is None else int(r.passed)) for r in rs if r.id != "timing"} for k, rs in results.items()}
        entries[ref] = {"ref": ref, "prs": [{"number": p.number, "created_at": p.created_at,
                                             "changes": sum(f.additions + f.deletions for f in p.files), "reactions": p.reactions} for p in prs]}
        merged_nums = {int(m.rsplit("#", 1)[1]) for m in item["merged"]}
        for p in prs:
            csv_rows.append({"issue": ref, "pr": p.number, "outcome": item["outcome"], "merged": int(p.number in merged_nums),
                             "changes": entries[ref]["prs"][[q.number for q in prs].index(p.number)]["changes"], "reactions": p.reactions,
                             **{cid: ("" if v is None else v) for cid, v in features[ref][p.number].items()}})
        if item["outcome"] == "one-merged":
            truth[ref] = next(iter(merged_nums))
    one = sorted(truth)
    rr, top, errors = [], [], []
    for ref in one:
        sc = {n: cal._score(f, w["weights"]) for n, f in features[ref].items()}
        rr.append(cal.expected_rr(sc, truth[ref]))
        top.append(cal.expected_top1(sc, truth[ref]))
        if top[-1] < 1.0:
            tied = sum(1 for n, v in sc.items() if n != truth[ref] and v == sc[truth[ref]])
            errors.append({"issue": ref, "merged_pr": truth[ref], "rank": cal._truth_rank(features[ref], truth[ref], w["weights"]),
                           "tied_with": tied, "failed_checks_on_merged": sorted(c for c, v in features[ref][truth[ref]].items() if v == 0)})
    tool = {"top1": round(sum(top) / len(top), 4) if top else 0.0, "mrr": round(sum(rr) / len(rr), 4) if rr else 0.0,
            "n_issues": len(rr), "mrr_ci95": list(cal.bootstrap_ci(rr)) if rr else None, "tie_rule": "expected over ties"}
    baselines_m = cal.baseline_mrr([entries[r] for r in one], truth)
    loio = cal.fit_weights_loio({r: features[r] for r in one}, truth) if len(one) >= 2 else None
    calib = None
    metrics = {"tool": tool, "baselines": baselines_m, "loio": loio, "weights_version": w["version"], "controls": controls,
               "kai_calls": getattr(kai, "spent_calls", 0), "kai_micro_usd": round(getattr(kai, "spent_micro_usd", 0.0), 2),
               "diagnosis": diagnose({r: features[r] for r in features}, truth, labels_csv)}
    (out_dir / "scores.json").write_text(json.dumps(scores, sort_keys=True, indent=1, ensure_ascii=False), encoding="utf-8")
    if labels_csv:
        calib = cal.calibrate_files(labels_csv, out_dir / "scores.json", out_dir)
    cols = ["issue", "pr", "outcome", "merged", "changes", "reactions"] + sorted({c for row in csv_rows for c in row} - {"issue", "pr", "outcome", "merged", "changes", "reactions"})
    with (out_dir / "features.csv").open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(csv_rows)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    if raw_dir is None:
        (out_dir / "drift.json").write_text(json.dumps(drift, indent=1), encoding="utf-8")
    fig = _figures(out_dir, metrics)
    (out_dir / "REPORT.md").write_text(render_report(manifest, metrics, errors, calib, fig, label_note), encoding="utf-8")
    return {"metrics": metrics, "drift": drift, "errors": errors}


def _label_note(study_dir: Path | None) -> str | None:
    p = study_dir / "spot_check_summary.json" if study_dir else None
    if not p or not p.exists():
        return None
    s = json.loads(p.read_text(encoding="utf-8"))
    return (f"Labels were made blind (no tool output, no merge status) by a separate assistant session from study/RUBRIC.md; "
            f"the author spot-checked {s['sample_size']} random PRs (seed {s['seed']}) and agreed on {s['labels_agreed']}/{s['labels_checked']} "
            f"labels ({s['label_agreement']:.1%}) before correcting the one disagreement.")


def main(argv: list[str] | None = None) -> int:
    import argparse
    from .collect import collect
    from .github import GitHub
    from .kai import key_from_env

    p = argparse.ArgumentParser(prog="pr-triage study")
    sub = p.add_subparsers(dest="step", required=True)
    b = sub.add_parser("build", help="collect the dataset into a private raw directory and write the public manifest")
    b.add_argument("--raw", required=True)
    b.add_argument("--manifest", default="study/manifest.json")
    r = sub.add_parser("run", help="run checks and metrics; replays --raw, or re-fetches and reports drift")
    r.add_argument("--raw")
    r.add_argument("--manifest", default="study/manifest.json")
    r.add_argument("--out", default="study/results")
    r.add_argument("--labels")
    r.add_argument("--kai", action="store_true")
    r.add_argument("--max-kai-calls", type=int, default=50)
    r.add_argument("--cache", default=".pr-triage-cache")
    a = p.parse_args(argv)
    gh = GitHub()
    if a.step == "build":
        refs = find_issue_refs(gh)
        man = build_dataset(refs, Path(a.raw), collect_fn=lambda repo, n, out: collect(repo, n, gh, out),
                            enrich_fn=lambda s: add_head_files(s, gh))
        Path(a.manifest).parent.mkdir(parents=True, exist_ok=True)
        Path(a.manifest).write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(man["counts"]))
        return 0
    man = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    kai = Kai(key_from_env() if a.kai else None, Path(a.cache), max_calls=a.max_kai_calls, max_micro_usd=1_000_000)
    res = run_study(man, Path(a.raw) if a.raw else None, Path(a.out), kai,
                    refetch_fn=lambda repo, n, out: collect(repo, n, gh, out, resume=False),
                    labels_csv=Path(a.labels) if a.labels else None, label_note=_label_note(Path(a.labels).parent if a.labels else None))
    print(json.dumps({"tool": res["metrics"]["tool"], "kai_calls": res["metrics"]["kai_calls"],
                      "kai_micro_usd": res["metrics"]["kai_micro_usd"]}))
    return 0


def render_report(manifest: dict, m: dict, errors: list[dict], calib: dict | None, figure_line: str,
                  label_note: str | None = None) -> str:
    c = manifest["counts"]
    t = m["tool"]
    ci = f" (95% CI {t['mrr_ci95'][0]:.2f}-{t['mrr_ci95'][1]:.2f})" if t.get("mrr_ci95") else ""
    lines = [
        "# Study: does pr-triage rank the PR a maintainer merged first?", "",
        "## Question", "",
        "When a bounty issue draws several pull requests, does pr-triage put the one the maintainer merged at rank 1, and does it beat simple orderings?", "",
        "## Data", "",
        f"Collected {manifest['collected_at']} with pr-triage {manifest.get('tool_version', '?')}. Method: {manifest['method']}.",
        f"Issues seen {c['issues_seen']}; kept {c['kept']} with at least two linked PRs ({c['prs']} PRs); "
        f"{c['one_merged']} with exactly one merged PR form the evaluation set; {c['below_min_prs']} below the two-PR minimum.", "",
    ]
    for e in manifest["exclusions"]:
        lines.append(f"- Excluded {e['ref']}: {e['reason']}.")
    lines += ["", "Published data are references, hashes and derived check values only; contributors' text stays out of this repository.", "",
              "## Method", "",
              "Deterministic checks always run; Kai checks are advisory and run only with a key. A PR's score is the weighted share of evaluated checks it passes; "
              "ties are broken uniformly at random for the tool and every baseline alike (expected reciprocal rank and expected top-1). Baselines: random order (exact expectation), earliest PR first, smallest diff first, most reactions first. "
              "Weights are fitted by leave-one-issue-out coordinate search on mean reciprocal rank.", "",
              f"Weights used for the headline numbers: `{m['weights_version']}`. Kai calls: {m['kai_calls']} ({m['kai_micro_usd']} micro-USD).", "",
              "## Results", "",
              "| Ordering | Top-1 | MRR | Issues |", "|---|---:|---:|---:|",
              f"| pr-triage | {t['top1']:.2f} | {t['mrr']:.2f}{ci} | {t['n_issues']} |"]
    lines += [f"| {name} | {b['top1']:.2f} | {b['mrr']:.2f} | {b['n_issues']} |" for name, b in m["baselines"].items()]
    lines += ["", figure_line, ""]
    if m.get("loio"):
        lines += [f"Leave-one-issue-out MRR with fitted weights: {m['loio']['loio_mrr']:.2f}. Fitted weights: "
                  + ", ".join(f"{k} {v:g}" for k, v in sorted(m["loio"]["weights"].items())) + ".", ""]
    ctrl = m.get("controls") or []
    if ctrl and all(x.get("result") == "not run" for x in ctrl):
        lines += ["Kai controls: not run (no key).", ""]
    elif ctrl:
        lines += ["Kai controls: " + ", ".join(f"{x['question']}/{'pos' if x['expect'] else 'neg'} {'pass' if x.get('pass') else 'FAIL' if 'pass' in x else x.get('result')}" for x in ctrl) + ".", ""]
    if calib:
        lines += ["Per-check agreement with manual labels: see `calibration.json`.", ""]
    d = m.get("diagnosis") or {}
    if d:
        lines += ["## Diagnosis", ""]
        if "label_ranker" in d:
            lr, am, an = d["label_ranker"], d["acceptable_among_merged"], d["acceptable_among_not_merged"]
            lines += [f"Ranking by the manual labels themselves (addresses the issue, no scope creep, no unsupported claims) gives "
                      f"top-1 {lr['top1']:.2f} and MRR {lr['mrr']:.2f}. Labelled acceptable: {am[0]}/{am[1]} merged PRs and "
                      f"{an[0]}/{an[1]} of the others. When several competing PRs are acceptable, which one a maintainer merges "
                      "depends on things these checks do not measure, so merge order is a weak target for a quality ranker.", ""]
        lines += ["| Check | Pass rate, merged | Pass rate, not merged |", "|---|---:|---:|"]
        for c, pr in d["pass_rates"].items():
            (ms, mn), (os_, on) = pr["merged"], pr["not_merged"]
            if mn or on:
                lines.append(f"| {c} | {ms}/{mn} | {os_}/{on} |")
        if d.get("never_fail"):
            lines += ["", "Checks that never failed on this data (they cannot separate PRs here): " + ", ".join(d["never_fail"]) + "."]
        lines.append("")
    lines += ["## Errors", ""]
    lines += [f"- {e['issue']}: merged #{e['merged_pr']} not uniquely first (pessimistic rank {e['rank']}, tied with {e['tied_with']}); failed checks on it: {', '.join(e['failed_checks_on_merged']) or 'none'}." for e in errors] or ["- None."]
    lines += ["", "## Limits", "",
              "One organisation's bounty program; a small number of issues; maintainers' merge decisions are the ground truth, and they can merge for reasons no check sees. "
              "Manual labels, where used, are made by an assistant from a written rubric and spot-checked by the author. Kai results are model opinions."
              + (f" {label_note}" if label_note else ""), "",
              "## Reproduce", "", "```", "python study/build_dataset.py --raw <private dir>   # or reuse a saved raw snapshot",
              "python study/run_study.py --raw <private dir>      # replays; without --raw it re-fetches and reports drift", "```", ""]
    return "\n".join(lines)
