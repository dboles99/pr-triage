"""Calibration harness: measure checks and model questions against labels; rank metrics, baselines, LOIO fitting.

Standard library only. Labels are 1/0; "?" (cannot tell) and None are skipped, never guessed.
"""
from __future__ import annotations

import csv
import json
import random
import statistics
from pathlib import Path


def binary_metrics(y_true: list[int], y_pred: list[int]) -> dict:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    n = len(y_true)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    acc = sum(1 for t, p in zip(y_true, y_pred) if t == p) / n if n else 0.0
    return {"accuracy": round(acc, 4), "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4), "n": n}


def brier(y_true: list[int], p: list[float]) -> float:
    return round(sum((pi - ti) ** 2 for ti, pi in zip(y_true, p)) / len(y_true), 4) if y_true else 0.0


def reliability(y_true: list[int], p: list[float], bins: int = 10) -> list[dict]:
    rows = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, pi in enumerate(p) if (lo <= pi < hi) or (b == bins - 1 and pi == 1.0)]
        rows.append({"bin_low": round(lo, 4), "bin_high": round(hi, 4), "n": len(idx),
                     "mean_p": round(statistics.fmean(p[i] for i in idx), 4) if idx else None,
                     "frac_true": round(statistics.fmean(y_true[i] for i in idx), 4) if idx else None})
    return rows


def auc(y_true: list[int], p: list[float]) -> float | None:
    pos = [pi for ti, pi in zip(y_true, p) if ti == 1]
    neg = [pi for ti, pi in zip(y_true, p) if ti == 0]
    if not pos or not neg:
        return None
    wins = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def choose_threshold(y_true: list[int], p: list[float], objective: str = "f1") -> dict:
    table = []
    for t in sorted(set(p)):
        m = binary_metrics(y_true, [1 if pi >= t else 0 for pi in p])
        table.append({"threshold": t, **m})
    best = max(table, key=lambda r: (r[objective], -r["threshold"])) if table else {}
    return {"threshold": best.get("threshold"), "precision": best.get("precision"), "recall": best.get("recall"),
            "f1": best.get("f1"), "table": table}


def rank_metrics(ranked: list[list[int]], truth: list[int]) -> dict:
    rr = [1 / (r.index(t) + 1) if t in r else 0.0 for r, t in zip(ranked, truth)]
    return {"top1": round(sum(1 for x in rr if x == 1.0) / len(rr), 4) if rr else 0.0,
            "mrr": round(statistics.fmean(rr), 4) if rr else 0.0, "n_issues": len(rr)}


def baselines(issues: list[dict]) -> dict[str, list[list[int]]]:
    rng = random.Random(0)
    out = {"random": [], "earliest": [], "smallest_diff": [], "most_reactions": []}
    for i in issues:
        prs = i["prs"]
        nums = [p["number"] for p in prs]
        shuffled = nums[:]
        rng.shuffle(shuffled)
        out["random"].append(shuffled)
        out["earliest"].append([p["number"] for p in sorted(prs, key=lambda p: (p["created_at"], p["number"]))])
        out["smallest_diff"].append([p["number"] for p in sorted(prs, key=lambda p: (p["changes"], p["number"]))])
        out["most_reactions"].append([p["number"] for p in sorted(prs, key=lambda p: (-p["reactions"], p["number"]))])
    return out


def _score(feats: dict, weights: dict) -> float:
    num = den = 0.0
    for cid, v in feats.items():
        w = weights.get(cid, 0.0)
        if v is None or w == 0:
            continue
        den += w
        num += w * float(v)
    return num / den if den else 0.0


def expected_rr(scores: dict, truth, higher_is_better: bool = True) -> float:
    """Expected reciprocal rank of `truth` when ties are broken uniformly at random.
    One rule for the tool and every baseline, so no ordering gets a free tie-break."""
    if truth not in scores:
        return 0.0
    s = scores[truth]
    better = sum(1 for n, v in scores.items() if n != truth and ((v > s) if higher_is_better else (v < s)))
    tied = 1 + sum(1 for n, v in scores.items() if n != truth and v == s)
    return sum(1 / (better + j) for j in range(1, tied + 1)) / tied


def expected_top1(scores: dict, truth, higher_is_better: bool = True) -> float:
    """Probability `truth` is ranked first when ties are broken uniformly at random."""
    if truth not in scores:
        return 0.0
    s = scores[truth]
    if any(((v > s) if higher_is_better else (v < s)) for n, v in scores.items() if n != truth):
        return 0.0
    return 1.0 / (1 + sum(1 for n, v in scores.items() if n != truth and v == s))


def random_mrr(sizes: list[int]) -> float:
    """Expected MRR of a uniformly random order: mean over issues of H_n / n."""
    return sum(sum(1 / k for k in range(1, n + 1)) / n for n in sizes) / len(sizes) if sizes else 0.0


def baseline_mrr(issues: list[dict], truth: dict) -> dict:
    """MRR and expected top-1 of simple orderings, ties handled exactly like the tool (expected_rr)."""
    keys = {"earliest": (lambda p: p["created_at"], False), "smallest_diff": (lambda p: p["changes"], False),
            "most_reactions": (lambda p: p["reactions"], True)}
    out = {}
    for name, (key, hib) in keys.items():
        rr = [expected_rr({p["number"]: key(p) for p in i["prs"]}, truth[i["ref"]], hib) for i in issues]
        top = [expected_top1({p["number"]: key(p) for p in i["prs"]}, truth[i["ref"]], hib) for i in issues]
        out[name] = {"top1": round(sum(top) / len(top), 4) if top else 0.0, "mrr": round(sum(rr) / len(rr), 4) if rr else 0.0, "n_issues": len(rr)}
    sizes = [len(i["prs"]) for i in issues]
    out["random"] = {"top1": round(sum(1 / n for n in sizes) / len(sizes), 4) if sizes else 0.0, "mrr": round(random_mrr(sizes), 4), "n_issues": len(sizes)}
    return out


def _truth_rank(prs: dict, truth, weights: dict) -> int | None:
    """Pessimistic rank (ties count against the true PR). Kept for diagnostics; metrics use expected_rr."""
    if truth not in prs:
        return None
    s = _score(prs[truth], weights)
    return 1 + sum(1 for n, f in prs.items() if n != truth and _score(f, weights) >= s)


def tool_rr(prs: dict, truth, weights: dict) -> float:
    return expected_rr({n: _score(f, weights) for n, f in prs.items()}, truth)


def _mrr(features: dict, truth: dict, weights: dict) -> float:
    rr = [tool_rr(features[i], truth[i], weights) for i in features]
    return statistics.fmean(rr) if rr else 0.0


def _fit(features: dict, truth: dict, grid: list[float]) -> dict:
    ids = sorted({c for prs in features.values() for f in prs.values() for c in f})
    w = {c: 1.0 for c in ids}
    best = _mrr(features, truth, w)
    for _ in range(2):  # two coordinate passes
        for c in ids:
            for g in grid:
                trial = {**w, c: g}
                m = _mrr(features, truth, trial)
                if m > best + 1e-12:
                    best, w = m, trial
    return w


def fit_weights_loio(features: dict, truth: dict, grid: list[float] = (0, 0.5, 1, 2)) -> dict:
    """features {issue: {pr: {check_id: 1|0|None}}}, truth {issue: merged_pr}. Leave-one-issue-out MRR plus a final fit on all."""
    grid = list(grid)
    folds = {}
    for k in sorted(features):
        train = {i: f for i, f in features.items() if i != k}
        w = _fit(train, {i: truth[i] for i in train}, grid)
        folds[k] = tool_rr(features[k], truth[k], w)
    final = _fit(features, truth, grid)
    return {"weights": final, "folds": folds, "loio_mrr": round(statistics.fmean(folds.values()), 4) if folds else 0.0}


def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(n))
    return (round(means[int(0.025 * n)], 4), round(means[int(0.975 * n) - 1], 4))


LABELS = ("addresses_issue", "scope_creep", "unsupported_claims")
# Which manual label each deterministic check is evidence for, and the label value a PASS predicts.
# Checks with no matching label (hidden_text, payment_request, ci_state, duplicate_of, timing) are not scored against labels.
PAIRS = {"touches_target": ("addresses_issue", 1), "criteria_static": ("addresses_issue", 1), "residue": ("addresses_issue", 1),
         "scope_creep": ("scope_creep", 0), "claim_vs_diff": ("unsupported_claims", 0)}


def calibrate_files(labels_csv: Path, scores_json: Path, out_dir: Path) -> dict:
    labels = {}
    with Path(labels_csv).open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            labels[(row["issue"], str(row["pr"]))] = {k: int(row[k]) for k in LABELS if row.get(k) in ("0", "1")}
    scores = json.loads(Path(scores_json).read_text(encoding="utf-8"))
    checks: dict = {}
    models: dict = {}
    ids = sorted({c for prs in scores.values() for r in prs.values() for c in r} & set(PAIRS))
    for cid in ids:
        lab, pass_means = PAIRS[cid]
        yt, yp = [], []
        for issue, prs in scores.items():
            for pr, res in prs.items():
                lv = labels.get((issue, str(pr)), {}).get(lab)
                r = res.get(cid)
                if lv is None or not r or r.get("passed") is None:
                    continue
                yt.append(lv)
                yp.append(pass_means if r["passed"] else 1 - pass_means)
        if yt:
            checks.setdefault(cid, {})[lab] = {**binary_metrics(yt, yp), "positive_class": f"{lab}=1"}
    for cid, lab in (("addresses_issue", "addresses_issue"), ("effort", "addresses_issue")):
        yt, p = [], []
        for issue, prs in scores.items():
            for pr, res in prs.items():
                lv = labels.get((issue, str(pr)), {}).get(lab)
                r = res.get(cid)
                if lv is None or not r or r.get("value") is None:
                    continue
                yt.append(lv)
                p.append(float(r["value"]))
        if yt:
            models[cid] = {"label": lab, "n": len(yt), "brier": brier(yt, p), "auc": auc(yt, p),
                           "reliability": reliability(yt, p), "threshold": choose_threshold(yt, p)}
    out = {"checks": checks, "models": models}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "calibration.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out
