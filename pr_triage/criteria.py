"""Find an issue's acceptance criteria and type the ones that can be checked mechanically."""
from __future__ import annotations

import re

from .model import Criterion, Issue

# Preferred sections first: an explicit criteria list beats a to-do list.
SECTIONS = (r"acceptance criteria", r"definition of done", r"what to do")
ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(?P<text>.+?)\s*$")
FILE = r"(?P<file>README(?:\.md)?|[\w./-]+\.[A-Za-z0-9]+)"
ABSENT = re.compile(FILE + r"\s+(?:must not|should not|does not|doesn't|shall not)\s+contain\s+`(?P<v>[^`]+)`", re.I)
CONTAINS = re.compile(FILE + r"\s+(?:must|should|shall)\s+contain\s+`(?P<v>[^`]+)`", re.I)
LINKS = re.compile(r"\b(?:links?|badges?|urls?)\b.*\breturns?\s+(?:HTTP\s+)?200\b", re.I)
IN_FILE = re.compile(r"\bin\s+(?:the\s+)?" + FILE, re.I)


def _norm_file(name: str) -> str:
    return "README.md" if name.lower() == "readme" else name


def _section_items(body: str, heading: str) -> list[str]:
    lines = body.splitlines()
    out, inside = [], False
    for line in lines:
        if re.match(r"^\s*#{1,6}\s+", line):
            inside = bool(re.match(r"^\s*#{1,6}\s+" + heading + r"\b", line, re.I))
            continue
        if inside:
            m = ITEM.match(line)
            if m:
                out.append(m.group("text"))
    return out


def _type(text: str) -> Criterion:
    m = ABSENT.search(text)
    if m:
        return Criterion(text, "absent", _norm_file(m.group("file")), m.group("v"))
    m = CONTAINS.search(text)
    if m:
        return Criterion(text, "contains", _norm_file(m.group("file")), m.group("v"))
    if LINKS.search(text):
        f = IN_FILE.search(text)
        return Criterion(text, "link_ok", _norm_file(f.group("file")) if f else None, None)
    return Criterion(text, "free_text")


def extract_criteria(issue: Issue) -> list[Criterion]:
    for heading in SECTIONS:
        items = _section_items(issue.body or "", heading)
        if items:
            return [_type(t) for t in items]
    return []
