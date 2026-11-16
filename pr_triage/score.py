"""Run every check on every PR and combine results into one score per PR."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .checks import DETERMINISTIC, criteria_static, duplicate_of
from .checks.model import model_checks
from .kai import Kai
from .model import CheckResult, Evidence, Issue, PR

WEIGHTS_FILE = Path(__file__).with_name("weights.json")


def load_weights(path: Path = WEIGHTS_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_checks(issue: Issue, prs: list[PR], fetch_text: Callable[[str, str, str], str | None] | None,
               kai: Kai | None, check_links: bool = False, head: Callable[[str], int] | None = None) -> dict[str, list[CheckResult]]:
    out: dict[int, list[CheckResult]] = {}
    for pr in prs:
        rs = [fn(issue, pr) for fn in DETERMINISTIC.values()]
        if fetch_text is None:
            rs.append(CheckResult("criteria_static", "deterministic", None, None, [Evidence("files", "not run (offline)")]))
        else:
            rs.append(criteria_static(issue, pr, fetch_text, check_links=check_links, head=head))
        rs.append(duplicate_of(pr, prs))
        rs.extend(model_checks(issue, pr, kai))
        out[pr.ref] = rs
    return out


def score(results: list[CheckResult], weights: dict) -> float:
    """Weighted share of evaluated checks that passed. Not-evaluated checks (passed=None) neither help nor hurt."""
    num = den = 0.0
    for r in results:
        w = float(weights.get(r.id, 0.0))
        if r.passed is None or w == 0:
            continue
        den += w
        num += w if r.passed else 0.0
    return round(num / den, 4) if den else 0.0
