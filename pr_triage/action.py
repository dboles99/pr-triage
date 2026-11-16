"""GitHub Action runner: on a maintainer's `/triage` issue comment, review the issue and post one summary comment."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .github import GitHub, GitHubError, NotFound

MARKER = "<!-- pr-triage -->"
MAINTAINERS = {"OWNER", "MEMBER", "COLLABORATOR"}
LIMIT = 60000


def should_run(event: dict) -> bool:
    c, issue = event.get("comment") or {}, event.get("issue") or {}
    return (event.get("action") == "created" and (c.get("body") or "").strip() == "/triage"
            and c.get("author_association") in MAINTAINERS and "pull_request" not in issue)


def has_write_access(gh: GitHub, repo: str, login: str) -> bool:
    """DESIGN 5.5: only users with write access may trigger a run (MEMBER/COLLABORATOR include read and triage roles)."""
    try:
        d = gh.get(f"repos/{repo}/collaborators/{login}/permission") or {}
    except (NotFound, GitHubError):
        return False
    return d.get("permission") in ("admin", "maintain", "write") or d.get("role_name") in ("admin", "maintain", "write")


def comment_body(report: dict, run_url: str) -> str:
    meta = report.get("meta", {})
    head = [MARKER, f"### pr-triage: {report['issue']['ref']}", "",
            f"Ranked {len(report['ranking'])} linked PRs · weights `{meta.get('weights_version')}` · Kai calls {meta.get('kai_calls', 0)}. "
            "This ranks and explains; the maintainer decides. Model results are advisory.", "",
            "| Rank | PR | Author | Score | Main reason |", "|---:|---|---|---:|---|"]
    tail = ["", f"Full report with evidence: {run_url} (artifact `pr-triage-report`)."]
    if meta.get("checks_not_run"):
        tail.insert(0, "")
        tail.insert(1, "Not run: " + ", ".join(meta["checks_not_run"]))
    rows, size = [], len("\n".join(head + tail))
    for r in report["ranking"]:
        line = f"| {r['rank']} | [#{r['number']}]({r['url']}) | {r['author'][:39]} | {r['score']:.2f} | {r['reason'][:140].replace('|', '/')} |"
        if size + len(line) + 80 > LIMIT:
            rows.append(f"| … | {len(report['ranking']) - len(rows)} more in the full report | | | |")
            break
        rows.append(line)
        size += len(line) + 1
    return "\n".join(head + rows + tail)


def upsert_comment(gh: GitHub, repo: str, number: int, body: str) -> None:
    existing = [c for c in gh.get(f"repos/{repo}/issues/{number}/comments?per_page=100") or [] if (c.get("body") or "").startswith(MARKER)]
    if existing:
        gh.send("PATCH", f"repos/{repo}/issues/comments/{existing[-1]['id']}", {"body": body})
    else:
        gh.send("POST", f"repos/{repo}/issues/{number}/comments", {"body": body})


def main() -> int:
    from .cli import main as cli_main
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    if not should_run(event):
        print("pr-triage: not a maintainer /triage comment on an issue; nothing to do")
        return 0
    repo, number = os.environ["GITHUB_REPOSITORY"], int(event["issue"]["number"])
    login = ((event.get("comment") or {}).get("user") or {}).get("login", "")
    if not has_write_access(GitHub(), repo, login):
        print("pr-triage: commenter lacks write access; nothing to do")
        return 0
    args = ["review", f"{repo}#{number}", "--out", "out", "--max-kai-calls", os.environ.get("MAX_KAI_CALLS", "20")]
    if not os.environ.get("HANZO_API_KEY"):
        args.append("--no-kai")
    code = cli_main(args)
    if code:
        return code
    report = json.loads(Path("out/report.json").read_text(encoding="utf-8"))
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    upsert_comment(GitHub(), repo, number, comment_body(report, run_url))
    print("pr-triage: comment posted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
