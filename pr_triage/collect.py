"""Collect one issue and every PR linked to it into a snapshot JSON (resumable)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from .github import GitHub, GitHubError, NotFound, ServerError

METHOD = "issue timeline cross-referenced events whose source is a pull request, any state, any repo"


def linked_prs(gh: GitHub, repo: str, number: int) -> list[tuple[str, int]]:
    seen: list[tuple[str, int]] = []
    for e in gh.get(f"repos/{repo}/issues/{number}/timeline?per_page=100") or []:
        src = (e.get("source") or {}).get("issue") or {}
        if e.get("event") == "cross-referenced" and src.get("pull_request"):
            key = ((src.get("repository") or {}).get("full_name") or repo, int(src["number"]))
            if key not in seen:
                seen.append(key)
    return seen


def _comment(c: dict) -> dict:
    return {"author": (c.get("user") or {}).get("login", ""), "body": c.get("body") or "", "created_at": c.get("created_at", "")}


def _collect_pr(gh: GitHub, repo: str, n: int) -> dict:
    d = gh.get(f"repos/{repo}/pulls/{n}")
    files = gh.get(f"repos/{repo}/pulls/{n}/files?per_page=100") or []
    head = d.get("head") or {}
    sha = head.get("sha", "")
    # Optional data: a token without `checks: read` gets 403 here. Missing CI data is "unknown", never a failure.
    checks_available = True
    try:
        runs = (gh.get(f"repos/{repo}/commits/{sha}/check-runs?per_page=100") or {}).get("check_runs", [])
    except ServerError:
        raise
    except (NotFound, GitHubError):
        runs, checks_available = [], False
    try:  # legacy commit statuses (DESIGN 5.1)
        statuses = (gh.get(f"repos/{repo}/commits/{sha}/status") or {}).get("statuses", [])
    except ServerError:
        raise
    except (NotFound, GitHubError):
        statuses = []
    try:
        reactions = ((gh.get(f"repos/{repo}/issues/{n}") or {}).get("reactions") or {}).get("total_count", 0)
    except ServerError:
        raise
    except (NotFound, GitHubError):
        reactions = 0
    return {
        "repo": repo, "number": n, "url": d.get("html_url", ""), "author": (d.get("user") or {}).get("login", ""),
        "title": d.get("title") or "", "body": d.get("body") or "", "state": d.get("state", ""),
        "merged": bool(d.get("merged") or d.get("merged_at")), "merged_at": d.get("merged_at"),
        "created_at": d.get("created_at", ""), "head_sha": sha, "head_available": head.get("repo") is not None,
        "files": [{"path": f["filename"], "status": f.get("status", ""), "additions": f.get("additions", 0),
                   "deletions": f.get("deletions", 0), **({"patch": f["patch"]} if "patch" in f else {})} for f in files],
        "comments": [_comment(c) for c in gh.get(f"repos/{repo}/issues/{n}/comments?per_page=100") or []],
        "reviews": [{"author": (r.get("user") or {}).get("login", ""), "state": r.get("state", ""), "body": r.get("body") or ""}
                    for r in gh.get(f"repos/{repo}/pulls/{n}/reviews?per_page=100") or []],
        "checks": [{"name": c.get("name", ""), "result": c.get("conclusion") or c.get("status", "")} for c in runs]
                  + [{"name": s.get("context", ""), "result": s.get("state", "")} for s in statuses],
        "checks_available": checks_available,
        "reactions": int(reactions or 0),
    }


def _write(out: Path, snap: dict) -> dict:
    body = {k: v for k, v in snap.items() if k != "sha256"}
    snap["sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    return snap


def collect(repo: str, number: int, gh: GitHub, out: Path, resume: bool = True) -> dict:
    out = Path(out)
    snap = None
    if resume and out.exists():
        old = json.loads(out.read_text(encoding="utf-8"))
        if not old.get("complete"):
            snap = old
    if snap is None:
        i = gh.get(f"repos/{repo}/issues/{number}")
        snap = {
            "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "method": METHOD, "complete": False,
            "issue": {"repo": repo, "number": number, "url": i.get("html_url", ""), "title": i.get("title") or "",
                      "body": i.get("body") or "", "labels": [l["name"] for l in i.get("labels", [])],
                      "created_at": i.get("created_at", ""), "state": i.get("state", ""),
                      "comments": [_comment(c) for c in gh.get(f"repos/{repo}/issues/{number}/comments?per_page=100") or []]},
            "linked": [list(x) for x in linked_prs(gh, repo, number)], "prs": [],
        }
    done = {(p["repo"], p["number"]) for p in snap["prs"]}
    done |= {(m.rsplit("#", 1)[0], int(m.rsplit("#", 1)[1])) for m in snap.get("missing", [])}
    for r, n in [tuple(x) for x in snap["linked"]]:
        if (r, n) in done:
            continue
        try:
            snap["prs"].append(_collect_pr(gh, r, n))
        except NotFound:
            miss = snap.setdefault("missing", [])
            if f"{r}#{n}" not in miss:
                miss.append(f"{r}#{n}")
        except Exception:
            _write(out, snap)  # keep what we have, mark incomplete, let the caller see the error
            raise
        _write(out, snap)
    snap["complete"] = True
    snap["counts"] = {"linked_prs": len(snap["linked"]), "collected_prs": len(snap["prs"]), "missing": len(snap.get("missing", []))}
    return _write(out, snap)
