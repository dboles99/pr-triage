"""Minimal GitHub REST client: UTF-8, pagination, rate-limit detection. Never logs headers or tokens."""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = "https://api.github.com/"


class RateLimited(Exception):
    def __init__(self, reset_at: str):
        super().__init__(f"GitHub rate limit reached; resets at {reset_at}")
        self.reset_at = reset_at


class NotFound(Exception):
    pass


class GitHubError(Exception):
    pass


class GitHub:
    def __init__(self, token: str | None = None, opener=None, timeout: int = 60):
        self.token = token if token is not None else (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout

    def _request(self, url: str):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "pr-triage"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, headers=headers)
        try:
            r = self.opener(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            h = e.headers or {}
            e.close()
            if e.code == 429 or (e.code == 403 and str(h.get("x-ratelimit-remaining", "")) == "0"):
                raise RateLimited(str(h.get("x-ratelimit-reset", "unknown"))) from None
            if e.code == 404:
                raise NotFound(url.replace(API, "")) from None
            raise GitHubError(f"HTTP {e.code} for {url.replace(API, '')}") from None
        with r:
            body = r.read().decode("utf-8", errors="replace")
            link = (r.headers.get("Link") if r.headers else None) or ""
        return json.loads(body) if body else None, link

    def send(self, method: str, path: str, body: dict) -> Any:
        """POST/PATCH a JSON body (used only by the Action to post its one comment)."""
        url = API + path.lstrip("/")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "pr-triage", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method=method, headers=headers)
        try:
            with self.opener(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            e.close()
            raise GitHubError(f"HTTP {e.code} for {method} {path}") from None
        return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        """GET a path under api.github.com; follows rel=next and concatenates list pages."""
        url = path if path.startswith("http") else API + path.lstrip("/")
        data, link = self._request(url)
        if not isinstance(data, list):
            return data
        out = list(data)
        while True:
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            if not m:
                return out
            data, link = self._request(m.group(1))
            out.extend(data or [])


def file_text_at(gh: GitHub, repo: str, path: str, sha: str) -> str | None:
    """File content at a commit, or None when the file, commit or fork is gone."""
    try:
        obj = gh.get(f"repos/{repo}/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(sha, safe='')}")
    except (NotFound, GitHubError, UnicodeError, ValueError):
        return None
    if not isinstance(obj, dict) or obj.get("encoding") != "base64":
        return None
    return base64.b64decode(obj.get("content", "")).decode("utf-8", errors="replace")
