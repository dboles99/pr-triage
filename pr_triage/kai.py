"""Hanzo Kai typed-decision client with an input-hash cache and a hard budget.

Contract (from @hanzo/mcp 2.4.22 and a live probe, 2026-11-16): POST {api}/v1/decisions
{"model": "kai", "state": ..., "questions": {name: {type, instructions?, criteria?}}} -> {"id", "answers",
"usage": {"input_tokens", ...}, "routing": {"checkpoint", ...}}. The key is never printed, logged or cached.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("HANZO_API_URL", "https://api.hanzo.ai")
MICRO_USD_PER_INPUT_TOKEN = 0.021  # $0.021 per million input tokens; output is free
KINDS = ("choice", "score", "noul")


class KaiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Kai HTTP {status}: {message}")
        self.status = status


class KaiRefused(KaiError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status, f"{code}: {message}")
        self.code = code


class BudgetExceeded(Exception):
    pass


def key_from_env() -> str | None:
    """HANZO_API_KEY, else the owner's HanzoLab vault (Windows SecretManagement). None if neither."""
    key = os.environ.get("HANZO_API_KEY")
    if key:
        return key
    try:
        r = subprocess.run(["pwsh", "-NoProfile", "-Command",
                            "Import-Module Microsoft.PowerShell.SecretManagement; "
                            "Get-Secret -Vault HanzoLab -Name HanzoApiKey -AsPlainText -ErrorAction Stop"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    key = r.stdout.strip()
    return key if r.returncode == 0 and key.startswith("sk-") else None


def check_questions(questions: dict) -> None:
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 100:
        raise ValueError("questions must be a dict of 1 to 100 questions")
    for name, q in questions.items():
        t, c = q.get("type"), q.get("criteria")
        if t not in KINDS:
            raise ValueError(f"question {name}: type must be one of {KINDS}")
        if t == "choice" and len(set(c if isinstance(c, list) else (c or {}))) < 2:
            raise ValueError(f"question {name}: choice needs at least 2 labels")
        if t == "score" and (not isinstance(c, list) or not c):
            raise ValueError(f"question {name}: score criteria must be levels, lowest first")


class Kai:
    def __init__(self, key: str | None, cache_dir: Path, max_calls: int = 50, max_micro_usd: int = 1_000_000,
                 opener=None, model: str = "kai", timeout: int = 90):
        self._key = key
        self.cache_dir = Path(cache_dir)
        self.max_calls, self.max_micro_usd = max_calls, max_micro_usd
        self.opener = opener or urllib.request.urlopen
        self.model, self.timeout = model, timeout
        self.spent_calls, self.spent_micro_usd = 0, 0.0

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _cache_path(self, payload: dict) -> Path:
        h = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.json"

    def decide(self, state: dict, questions: dict) -> dict:
        check_questions(questions)
        payload = {"model": self.model, "state": state, "questions": questions}
        cached = self._cache_path(payload)
        if cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))
        if not self.available:
            raise KaiError(0, "no Hanzo key")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        estimate = len(body) / 4 * MICRO_USD_PER_INPUT_TOKEN
        if self.spent_calls + 1 > self.max_calls or self.spent_micro_usd + estimate > self.max_micro_usd:
            raise BudgetExceeded(f"Kai budget reached: {self.spent_calls} calls, {self.spent_micro_usd:.1f} micro-USD")
        req = urllib.request.Request(API + "/v1/decisions", data=body, method="POST",
                                     headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json",
                                              "Accept": "application/json", "User-Agent": "pr-triage"})
        try:
            with self.opener(req, timeout=self.timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read()[:2000].decode("utf-8", "replace")
            e.close()
            try:
                err = json.loads(raw).get("error") or {}
            except (ValueError, AttributeError):
                err = {}
            msg = ((err.get("message") if isinstance(err, dict) else str(err)) or raw[:200]).replace(self._key, "<key>")
            if e.code in (402, 429) and isinstance(err, dict) and err.get("code"):
                raise KaiRefused(e.code, err["code"], msg) from None
            raise KaiError(e.code, msg) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise KaiError(0, f"{type(e).__name__}: request failed") from None
        answers = d.get("answers") if isinstance(d, dict) else None
        if not isinstance(answers, dict) or any(not isinstance(answers.get(n), dict) for n in questions):
            raise KaiError(200, "response is not a complete decision")
        self.spent_calls += 1
        self.spent_micro_usd += (d.get("usage") or {}).get("input_tokens", len(body) / 4) * MICRO_USD_PER_INPUT_TOKEN
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return d
