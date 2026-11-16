"""Check registry.

DETERMINISTIC holds checks that need only (issue, pr). criteria_static (needs file text at the PR
head) and duplicate_of (needs the other PRs) are run by score.run_checks with their extra inputs.
"""
from .content import ci_state, criteria_static, duplicate_of, hidden_text, payment_request, residue, timing
from .diff import claim_vs_diff, scope_creep, touches_target

DETERMINISTIC = {
    "touches_target": touches_target,
    "scope_creep": scope_creep,
    "claim_vs_diff": claim_vs_diff,
    "residue": lambda issue, pr: residue(pr),
    "hidden_text": lambda issue, pr: hidden_text(pr),
    "payment_request": payment_request,
    "ci_state": lambda issue, pr: ci_state(pr),
    "timing": timing,
}

__all__ = ["DETERMINISTIC", "criteria_static", "duplicate_of"]
