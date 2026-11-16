"""Command line entry point."""
from __future__ import annotations

import argparse
import functools
import json
import re
import urllib.request
from pathlib import Path

from . import __version__

TARGET = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+)#(?P<n>\d+)$")


def _head_status(url: str) -> int:
    if not url.startswith(("https://", "http://")):
        return 0
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "pr-triage"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def cmd_review(args) -> int:
    from .collect import collect
    from .github import GitHub, file_text_at
    from .kai import Kai, key_from_env
    from .model import load_snapshot
    from .report import render
    from .score import load_weights, run_checks, score

    m = TARGET.match(args.target)
    if not m:
        raise SystemExit("target must look like OWNER/REPO#N")
    out = Path(args.out or f"out/{m['repo'].replace('/', '_')}_{m['n']}")
    out.mkdir(parents=True, exist_ok=True)
    gh = None if args.offline else GitHub()
    snap_path = Path(args.snapshot) if args.snapshot else out / "snapshot.json"
    if not args.snapshot:
        if gh is None:
            raise SystemExit("--offline needs --snapshot")
        collect(m["repo"], int(m["n"]), gh, snap_path)
    issue, prs = load_snapshot(snap_path)
    snap_time = json.loads(snap_path.read_text(encoding="utf-8")).get("collected_at", "?")
    kai = Kai(key_from_env() if args.kai else None, Path(args.cache), max_calls=args.max_kai_calls)
    fetch = None if gh is None else functools.partial(file_text_at, gh)
    results = run_checks(issue, prs, fetch, kai, check_links=args.links, head=_head_status)
    w = load_weights()
    scores = {n: score(rs, w["weights"]) for n, rs in results.items()}
    md, js = render(issue, prs, results, scores, {"snapshot_time": snap_time, "tool_version": __version__,
                                                   "weights_version": w["version"], "weights": w["weights"],
                                                   "kai_calls": kai.spent_calls})
    (out / "report.md").write_text(md, encoding="utf-8")
    (out / "report.json").write_text(json.dumps(js, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"report: {out / 'report.md'} ({len(prs)} PRs, Kai calls {kai.spent_calls})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pr-triage", description="Rank an issue's competing pull requests with evidence.")
    p.add_argument("--version", action="store_true", help="print the version and exit")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("review", help="rank the PRs linked to one issue")
    r.add_argument("target", help="OWNER/REPO#N")
    r.add_argument("--snapshot", help="use a saved snapshot instead of collecting")
    r.add_argument("--out", help="output directory (default out/OWNER_REPO_N)")
    r.add_argument("--kai", dest="kai", action="store_true", default=True, help="run Kai checks when a key is available (default)")
    r.add_argument("--no-kai", dest="kai", action="store_false", help="skip Kai checks")
    r.add_argument("--max-kai-calls", type=int, default=50)
    r.add_argument("--links", action="store_true", help="check link criteria over the network")
    r.add_argument("--offline", action="store_true", help="no network: needs --snapshot; file-content criteria not run")
    r.add_argument("--cache", default=".pr-triage-cache", help="Kai response cache directory")
    c = sub.add_parser("calibrate", help="measure checks and model questions against manual labels")
    c.add_argument("--labels", required=True)
    c.add_argument("--scores", required=True)
    c.add_argument("--out", required=True)
    lab = sub.add_parser("label", help="blind manual labelling")
    lsub = lab.add_subparsers(dest="label_cmd", required=True)
    le = lsub.add_parser("export", help="write a blank labels CSV for every PR in the snapshots")
    le.add_argument("--snapshots", required=True, help="directory of snapshot JSON files")
    le.add_argument("--out", required=True)
    le.add_argument("--labeller", default="assistant")
    ls = lsub.add_parser("sample", help="draw a reproducible spot-check sample")
    ls.add_argument("--labels", required=True)
    ls.add_argument("--n", type=int, default=20)
    ls.add_argument("--seed", type=int, default=0)
    ls.add_argument("--out", required=True)
    st = sub.add_parser("study", help="build the dataset or run the study (see `pr-triage study -h`)", add_help=False)
    st.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"pr-triage {__version__}")
        return 0
    if args.cmd == "review":
        return cmd_review(args)
    if args.cmd == "study":
        from .study import main as study_main
        return study_main(args.rest)
    if args.cmd == "label":
        import csv as _csv
        from .label import COLUMNS, label_rows, spot_check_sample, write_labels
        if args.label_cmd == "export":
            rows = label_rows(sorted(Path(args.snapshots).glob("*.json")))
            write_labels(rows, Path(args.out), args.labeller)
            print(f"labels: {args.out} ({len(rows)} PRs, blank, blind)")
        else:
            rows = spot_check_sample(Path(args.labels), args.n, args.seed)
            with Path(args.out).open("w", encoding="utf-8", newline="") as f:
                w = _csv.DictWriter(f, fieldnames=COLUMNS + ["owner_agrees"], extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            print(f"sample: {args.out} ({len(rows)} rows, seed {args.seed})")
        return 0
    if args.cmd == "calibrate":
        from .calibrate import calibrate_files
        out = calibrate_files(Path(args.labels), Path(args.scores), Path(args.out))
        print(f"calibration: {Path(args.out) / 'calibration.json'} ({len(out['checks'])} checks, {len(out['models'])} model questions)")
        return 0
    if not args.cmd:
        build_parser().print_help()
        return 1
    print(f"{args.cmd}: not implemented")
    return 1
