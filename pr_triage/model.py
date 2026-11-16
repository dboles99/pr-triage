"""Plain data types shared by every stage. Snapshots are JSON; these are their in-memory form."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileChange:
    path: str
    status: str
    additions: int
    deletions: int
    patch: str | None  # GitHub omits the patch for large or binary files


@dataclass
class PR:
    repo: str
    number: int
    url: str
    author: str
    title: str
    body: str
    state: str
    merged: bool
    created_at: str
    head_sha: str
    head_available: bool
    files: list[FileChange] = field(default_factory=list)
    comments: list[dict] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    reactions: int = 0

    @property
    def ref(self) -> str:
        return f"{self.repo}#{self.number}"


@dataclass
class Issue:
    repo: str
    number: int
    url: str
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    created_at: str = ""
    comments: list[dict] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.repo}#{self.number}"


@dataclass
class Criterion:
    text: str
    kind: str  # contains | absent | link_ok | free_text
    target: str | None = None
    value: str | None = None


@dataclass
class Evidence:
    where: str
    detail: str


@dataclass
class CheckResult:
    id: str
    kind: str  # deterministic | model
    value: float | None
    passed: bool | None  # None = not evaluable or not run; never counted as a failure
    evidence: list[Evidence] = field(default_factory=list)


def _pr(d: dict) -> PR:
    files = [FileChange(f["path"], f.get("status", ""), int(f.get("additions", 0)), int(f.get("deletions", 0)), f.get("patch"))
             for f in d.get("files", [])]
    return PR(repo=d["repo"], number=int(d["number"]), url=d.get("url", ""), author=d.get("author", ""),
              title=d.get("title", "") or "", body=d.get("body", "") or "", state=d.get("state", ""),
              merged=bool(d.get("merged")), created_at=d.get("created_at", ""), head_sha=d.get("head_sha", ""),
              head_available=bool(d.get("head_available", True)), files=files, comments=list(d.get("comments", [])),
              reviews=list(d.get("reviews", [])), checks=list(d.get("checks", [])), reactions=int(d.get("reactions", 0)))


def snapshot_from_dict(d: dict) -> tuple[Issue, list[PR]]:
    i = d["issue"]
    issue = Issue(repo=i["repo"], number=int(i["number"]), url=i.get("url", ""), title=i.get("title", "") or "",
                  body=i.get("body", "") or "", labels=list(i.get("labels", [])), created_at=i.get("created_at", ""),
                  comments=list(i.get("comments", [])))
    return issue, [_pr(p) for p in d.get("prs", [])]


def load_snapshot(path: Path) -> tuple[Issue, list[PR]]:
    return snapshot_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
