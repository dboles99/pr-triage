"""Checks that compare a PR's changed files and claims with what the issue asks for."""
from __future__ import annotations

import posixpath
import re

from ..criteria import extract_criteria
from ..model import CheckResult, Evidence, Issue, PR

PATH = re.compile(r"`?(?P<p>(?:[\w.-]+/)*[\w.-]+\.(?:md|go|py|js|ts|tsx|json|ya?ml|toml|mod|sum|txt|rs|cfg|ini|sh|ps1))`?", re.I)
KNOWN = re.compile(r"\b(README|CHANGELOG|LICENSE|CONTRIBUTING)\b")
STOP = {"the", "a", "an", "old", "section", "block", "part", "lines", "line", "code", "and", "of", "from", "to", "all"}
REMOVED = re.compile(r"\bremov(?:ed|es|ing)?\s+((?:[`\w.-]+\s+){0,3}[`\w.-]+)", re.I)
TESTS = re.compile(r"\badd(?:ed|s|ing)?\s+(?:unit\s+|new\s+)?tests?\b", re.I)


def targets(issue: Issue) -> set[str]:
    found = {m.group("p") for m in PATH.finditer(f"{issue.title}\n{issue.body}")}
    found |= {f"{m.group(1)}.md" if m.group(1) != "LICENSE" else "LICENSE" for m in KNOWN.finditer(issue.body or "")}
    found |= {c.target for c in extract_criteria(issue) if c.target}
    return {f for f in found if not f.startswith(("http", "www."))}


def _in_scope(path: str, tgts: set[str]) -> bool:
    if path in tgts:
        return True
    # Same-directory scope only for targets below the root; a root README does not make every root file in scope.
    return any(posixpath.dirname(t) and path.startswith(posixpath.dirname(t) + "/") for t in tgts)


def touches_target(issue: Issue, pr: PR) -> CheckResult:
    tgts = targets(issue)
    if not tgts:
        return CheckResult("touches_target", "deterministic", None, None, [Evidence("issue", "no target files named")])
    hit = [f.path for f in pr.files if f.path in tgts]
    ev = [Evidence(p, "changes a file the issue names") for p in hit] or [Evidence("files", "changes none of: " + ", ".join(sorted(tgts)))]
    return CheckResult("touches_target", "deterministic", float(bool(hit)), bool(hit), ev)


def scope_creep(issue: Issue, pr: PR) -> CheckResult:
    tgts = targets(issue)
    if not tgts:
        return CheckResult("scope_creep", "deterministic", None, None, [Evidence("issue", "no target files named")])
    extra = [f.path for f in pr.files if not _in_scope(f.path, tgts)]
    return CheckResult("scope_creep", "deterministic", float(len(extra)), not extra,
                       [Evidence(p, "outside the issue's files") for p in extra])


def _post_image(patch: str) -> str:
    """Lines present after the change: added and unchanged context lines."""
    return "\n".join(l[1:] for l in patch.splitlines() if l[:1] in "+ " and not l.startswith("+++"))


def claim_vs_diff(issue: Issue, pr: PR) -> CheckResult:
    body = pr.body or ""
    ev: list[Evidence] = []
    unknown = False
    for m in REMOVED.finditer(body):
        words = [w.strip("`.,") for w in m.group(1).split()]
        keys = [w for w in words if w and w.lower() not in STOP]
        if not keys:
            continue
        key = keys[0]
        patches = [(f.path, f.patch) for f in pr.files]
        if any(p is None for _, p in patches) and not any(p and key in p for _, p in patches):
            unknown = True
            ev.append(Evidence("diff", f"claim 'removed {key}': patch not available for some files"))
            continue
        still = [path for path, p in patches if p and key in _post_image(p)]
        for path in still:
            ev.append(Evidence(path, f"claims it removed '{key}' but '{key}' is still in the changed file"))
    if TESTS.search(body) and not any(re.search(r"(^|/)(tests?|spec)(/|_)|_test\.|\.test\.|test_", f.path) for f in pr.files):
        ev.append(Evidence("files", "claims added tests but no test files changed"))
    failed = [e for e in ev if "patch not available" not in e.detail]
    if failed:
        return CheckResult("claim_vs_diff", "deterministic", float(len(failed)), False, ev)
    if unknown:
        return CheckResult("claim_vs_diff", "deterministic", None, None, ev)
    return CheckResult("claim_vs_diff", "deterministic", 0.0, True, ev)
