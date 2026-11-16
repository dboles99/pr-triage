import json
import re
import unittest
from pathlib import Path

from pr_triage.action import MARKER, comment_body, should_run, upsert_comment
from pr_triage.github import GitHub
from tests.fakes import FakeGitHub

ROOT = Path(__file__).resolve().parents[1]


def event(body="/triage", assoc="MEMBER", is_pr=False):
    issue = {"number": 7}
    if is_pr:
        issue["pull_request"] = {"url": "x"}
    return {"action": "created", "comment": {"body": body, "author_association": assoc}, "issue": issue}


class ActionTests(unittest.TestCase):
    def test_trigger_guard_rejects_non_maintainer(self):
        self.assertTrue(should_run(event()))
        self.assertTrue(should_run(event(assoc="OWNER")))
        self.assertFalse(should_run(event(assoc="CONTRIBUTOR")))
        self.assertFalse(should_run(event(assoc="NONE")))
        self.assertFalse(should_run(event(body="/triage please")))
        self.assertFalse(should_run(event(is_pr=True)))
        self.assertFalse(should_run({"action": "edited", **{k: v for k, v in event().items() if k != "action"}}))

    def test_comment_body_under_limit_and_marked(self):
        report = {"issue": {"ref": "a/b#7"}, "meta": {"weights_version": "0-unfitted", "kai_calls": 0, "checks_not_run": {}},
                  "ranking": [{"rank": i, "number": i, "url": f"u{i}", "author": "x" * 50, "score": 0.5, "reason": "r" * 500}
                              for i in range(1, 400)]}
        body = comment_body(report, "https://example/run/1")
        self.assertTrue(body.startswith(MARKER))
        self.assertLess(len(body), 60000)
        self.assertIn("https://example/run/1", body)
        self.assertIn("advisory", body.lower())

    def test_upsert_updates_existing_marked_comment(self):
        fake = FakeGitHub({"repos/a/b/issues/7/comments?per_page=100": (200, {}, [{"id": 5, "body": MARKER + "\nold", "user": {"login": "github-actions[bot]"}}]),
                           "repos/a/b/issues/comments/5": (200, {}, {"id": 5})})
        upsert_comment(GitHub(token="t", opener=fake), "a/b", 7, MARKER + "\nnew")
        self.assertEqual(fake.requests[-1]["method"], "PATCH")
        self.assertEqual(json.loads(fake.requests[-1]["data"])["body"], MARKER + "\nnew")

    def test_upsert_creates_when_absent(self):
        fake = FakeGitHub({"repos/a/b/issues/7/comments?per_page=100": (200, {}, []),
                           "repos/a/b/issues/7/comments": (201, {}, {"id": 9})})
        upsert_comment(GitHub(token="t", opener=fake), "a/b", 7, MARKER + "\nnew")
        self.assertEqual(fake.requests[-1]["method"], "POST")

    def test_action_yml_has_no_checkout_of_pr_head(self):
        for p in (ROOT / "action.yml", ROOT / "examples" / "triage.yml"):
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("pull_request.head", text)
            self.assertNotIn("pull_request_target", text)
            self.assertIsNone(re.search(r"actions/checkout@[^\n]*\n(\s+with:\s*\n)?\s+ref:", text))
        self.assertIn("issue_comment", (ROOT / "examples" / "triage.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class PermissionTests(unittest.TestCase):
    def test_requires_write_permission(self):
        from pr_triage.action import has_write_access
        for perm, ok in (("admin", True), ("maintain", True), ("write", True), ("triage", False), ("read", False)):
            fake = FakeGitHub({"repos/a/b/collaborators/u/permission": (200, {}, {"permission": perm, "role_name": perm})})
            self.assertEqual(has_write_access(GitHub(token="t", opener=fake), "a/b", "u"), ok, perm)
        self.assertFalse(has_write_access(GitHub(token="t", opener=FakeGitHub({})), "a/b", "u"))


class MinorActionTests(unittest.TestCase):
    def test_upsert_only_edits_bot_comment(self):
        fake = FakeGitHub({"repos/a/b/issues/7/comments?per_page=100": (200, {}, [{"id": 5, "body": MARKER + "\nspoof", "user": {"login": "mallory"}}]),
                           "repos/a/b/issues/7/comments": (201, {}, {"id": 9})})
        upsert_comment(GitHub(token="t", opener=fake), "a/b", 7, MARKER + "\nnew")
        self.assertEqual(fake.requests[-1]["method"], "POST")

    def test_example_workflow_pins_a_version(self):
        text = (ROOT / "examples" / "triage.yml").read_text(encoding="utf-8")
        self.assertNotIn("pr-triage@main", text)
        self.assertRegex(text, r"dboles99/pr-triage@(v\d+\.\d+\.\d+|[0-9a-f]{40})")
