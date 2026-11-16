"""Blind manual labelling: export PRs without any tool output, record who labelled and when, sample for spot checks."""
from __future__ import annotations

import csv
import datetime as dt
import random
from pathlib import Path

from .model import load_snapshot

COLUMNS = ["issue", "pr", "url", "addresses_issue", "scope_creep", "unsupported_claims", "labeller", "labelled_at", "notes"]


def label_rows(snapshot_paths) -> list[dict]:
    rows = []
    for p in snapshot_paths:
        issue, prs = load_snapshot(Path(p))
        for pr in prs:
            rows.append({"issue": issue.ref, "pr": pr.number, "url": pr.url, "title": pr.title,
                         "files_changed": "; ".join(f.path for f in pr.files)})
    return rows


def write_labels(rows: list[dict], path: Path, labeller: str) -> None:
    today = dt.date.today().isoformat()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**{c: r.get(c, "") for c in COLUMNS}, "labeller": labeller, "labelled_at": r.get("labelled_at") or today})


def spot_check_sample(labels_csv: Path, n: int = 20, seed: int = 0) -> list[dict]:
    with Path(labels_csv).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return random.Random(seed).sample(rows, min(n, len(rows)))
