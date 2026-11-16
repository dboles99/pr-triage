"""Checks on what a PR's text and post-change files contain, plus duplicate and context checks."""
from __future__ import annotations

import datetime as dt
import difflib
import re
from typing import Callable

from ..criteria import extract_criteria
from ..model import CheckResult, Evidence, Issue, PR

RESIDUE = re.compile(r"===FILE:|===END_FILE===|Instruções para você|Passos para Submissão|^#+\s*Proposed README", re.I | re.M)
RESIDUE_PATH = re.compile(r"(^|/)(submissions?|solutions?)/|(^|/)SOLUTION\.md$", re.I)
HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
INVISIBLE = re.compile("[​‌‍‪-‮⁦-⁩]")
PAYMENT = re.compile(r"payout address|remit payment|bounty reward to|wallet address|\bUSDT\b|\bUSDC\b|\bTRC-?20\b|\bERC-?20\b", re.I)
POINTS_ONLY = re.compile(r"not money|reputation points|\bpoints\b(?![^\n]*\$)", re.I)
URL = re.compile(r"https?://[^\s)\]\"'<>`]+")


def _added(pr: PR) -> str:
    return "\n".join(l[1:] for f in pr.files if f.patch for l in f.patch.splitlines() if l.startswith("+") and not l.startswith("+++"))


def _changed_lines(pr: PR) -> str:
    return "\n".join(f.path + "\n" + "\n".join(l for l in (f.patch or "").splitlines() if l[:1] in "+-")
                     for f in sorted(pr.files, key=lambda f: f.path))


def criteria_static(issue: Issue, pr: PR, fetch_text: Callable[[str, str, str], str | None],
                    check_links: bool = False, head: Callable[[str], int] | None = None) -> CheckResult:
    crits = [c for c in extract_criteria(issue) if c.kind in ("contains", "absent", "link_ok") and c.target]
    if not crits:
        return CheckResult("criteria_static", "deterministic", None, None, [Evidence("issue", "no mechanically checkable criteria")])
    if not pr.head_available:
        return CheckResult("criteria_static", "deterministic", None, None, [Evidence("head", "PR head not available (fork deleted)")])
    ev, results, cache = [], [], {}
    for c in crits:
        if c.target not in cache:
            cache[c.target] = fetch_text(pr.repo, c.target, pr.head_sha)
        text = cache[c.target]
        if text is None:
            ev.append(Evidence(c.target, f"'{c.text}': file not readable at head, not evaluated"))
            continue
        if c.kind == "absent":
            ok = c.value not in text
            ev.append(Evidence(c.target, f"'{c.text}': {'absent' if ok else 'still contains `' + c.value + '`'}"))
        elif c.kind == "contains":
            ok = c.value in text
            ev.append(Evidence(c.target, f"'{c.text}': {'present' if ok else 'missing `' + c.value + '`'}"))
        else:
            if not (check_links and head):
                ev.append(Evidence(c.target, f"'{c.text}': link check not run (use --links)"))
                continue
            bad = [(u, s) for u in sorted(set(URL.findall(text))) if (s := head(u)) != 200]
            ok = not bad
            ev.append(Evidence(c.target, f"'{c.text}': " + ("all links 200" if ok else "; ".join(f"{u} -> {s}" for u, s in bad))))
        results.append(ok)
    if not results:
        return CheckResult("criteria_static", "deterministic", None, None, ev)
    return CheckResult("criteria_static", "deterministic", sum(results) / len(results), all(results), ev)


def duplicate_of(pr: PR, others: list[PR]) -> CheckResult:
    mine = _changed_lines(pr)
    best, ev, copied_from, unknown = 0.0, [], [], []
    for o in others:
        if o.repo == pr.repo and o.number == pr.number:
            continue
        theirs = _changed_lines(o)
        if mine == theirs:
            sim = 1.0 if mine else 0.0
        else:
            # Line-level similarity: character-level matching is quadratic and hangs on 100 KB diffs.
            a, b = mine.splitlines(), theirs.splitlines()
            sm = difflib.SequenceMatcher(None, a, b)
            sim = sm.ratio() if sm.real_quick_ratio() > best else 0.0
        best = max(best, sim)
        if mine and mine == theirs and any(f.patch is None for f in pr.files + o.files):
            unknown.append(o.ref)  # same paths, but without patches "identical" cannot be shown
            ev.append(Evidence(o.ref, "same changed paths; patch not available, identity not checked"))
            continue
        if mine and mine == theirs:
            if o.created_at < pr.created_at:  # the later PR is the copy
                copied_from.append(o.ref)
                ev.append(Evidence(o.ref, "identical changed lines, opened earlier"))
            else:
                ev.append(Evidence(o.ref, "identical changed lines, opened later (this PR is the original)"))
    if not copied_from and unknown:
        return CheckResult("duplicate_of", "deterministic", round(best, 4), None, ev)
    return CheckResult("duplicate_of", "deterministic", round(best, 4), not copied_from, ev)


def _no_patch_visible(pr: PR) -> bool:
    return bool(pr.files) and all(f.patch is None for f in pr.files)


def residue(pr: PR) -> CheckResult:
    ev = [Evidence("body" if src == "body" else "diff", f"answer/handoff residue: '{m.group(0)}'")
          for src, txt in (("body", pr.body or ""), ("diff", _added(pr))) for m in RESIDUE.finditer(txt)]
    ev += [Evidence(f.path, "solution document instead of an edit") for f in pr.files if RESIDUE_PATH.search(f.path)]
    if not ev and _no_patch_visible(pr):
        return CheckResult("residue", "deterministic", None, None, [Evidence("diff", "patch not available; diff not scanned")])
    return CheckResult("residue", "deterministic", float(len(ev)), not ev, ev)


def hidden_text(pr: PR) -> CheckResult:
    ev = []
    for src, txt in (("body", pr.body or ""), ("diff", _added(pr))):
        ev += [Evidence(src, f"HTML comment: {m.group(0)[:80]!r}") for m in HTML_COMMENT.finditer(txt)]
        ev += [Evidence(src, f"invisible/bidi control U+{ord(m.group(0)):04X}") for m in INVISIBLE.finditer(txt)]
    if not ev and _no_patch_visible(pr):
        return CheckResult("hidden_text", "deterministic", None, None, [Evidence("diff", "patch not available; diff not scanned")])
    return CheckResult("hidden_text", "deterministic", float(len(ev)), not ev, ev)


def payment_request(issue: Issue, pr: PR) -> CheckResult:
    text = "\n".join([pr.body or ""] + [c.get("body", "") for c in pr.comments if c.get("author") == pr.author])
    hits = sorted({m.group(0) for m in PAYMENT.finditer(text)})
    if not hits:
        return CheckResult("payment_request", "deterministic", 0.0, True, [])
    terms = "issue reward is points, not money" if POINTS_ONLY.search(issue.body or "") else "issue reward terms unclear"
    return CheckResult("payment_request", "deterministic", float(len(hits)), False,
                       [Evidence("body", f"payment wording {', '.join(hits)}; {terms}")])


def ci_state(pr: PR) -> CheckResult:
    if not pr.checks:
        return CheckResult("ci_state", "deterministic", None, None, [Evidence("checks", "no CI data (not a pass)")])
    bad = [c for c in pr.checks if str(c.get("result", "")).lower() in ("failure", "error", "cancelled", "timed_out", "action_required")]
    pending = [c for c in pr.checks if str(c.get("result", "")).lower() in ("queued", "in_progress", "pending", "waiting", "requested", "")]
    if not bad and pending:
        return CheckResult("ci_state", "deterministic", None, None, [Evidence(c.get("name", "check"), "not finished") for c in pending])
    return CheckResult("ci_state", "deterministic", float(len(bad)), not bad,
                       [Evidence(c.get("name", "check"), f"result {c.get('result')}") for c in (bad or pr.checks)])


def _ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def timing(issue: Issue, pr: PR) -> CheckResult:
    try:
        hours = round((_ts(pr.created_at) - _ts(issue.created_at)).total_seconds() / 3600, 1)
    except ValueError:
        return CheckResult("timing", "deterministic", None, None, [Evidence("dates", "unparseable timestamps")])
    return CheckResult("timing", "deterministic", hours, None, [Evidence("created_at", f"opened {hours} h after the issue")])
