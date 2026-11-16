import unittest
from pathlib import Path

from pr_triage.checks.diff import claim_vs_diff, scope_creep, touches_target
from pr_triage.model import FileChange, PR, load_snapshot

ISSUE, PRS = load_snapshot(Path(__file__).parent / "fixtures" / "snapshot_small.json")
GOOD, SOLUTION_DOC, CREEP = PRS


def pr_with(files, body):
    return PR(repo="acme/widget", number=99, url="", author="z", title="t", body=body, state="open", merged=False,
              created_at="", head_sha="x", head_available=True, files=files)


class DiffCheckTests(unittest.TestCase):
    def test_readme_issue_with_readme_change_passes_target(self):
        r = touches_target(ISSUE, GOOD)
        self.assertEqual((r.id, r.kind, r.passed), ("touches_target", "deterministic", True))

    def test_solution_doc_only_fails_target(self):
        self.assertFalse(touches_target(ISSUE, SOLUTION_DOC).passed)

    def test_gitignore_change_on_readme_issue_is_scope_creep(self):
        r = scope_creep(ISSUE, CREEP)
        self.assertFalse(r.passed)
        self.assertTrue(any(".gitignore" in e.where for e in r.evidence))
        self.assertTrue(scope_creep(ISSUE, GOOD).passed)

    def test_claim_removed_but_still_present(self):
        r = claim_vs_diff(ISSUE, CREEP)
        self.assertFalse(r.passed)
        details = " ".join(e.detail for e in r.evidence)
        self.assertIn("widgetc", details)
        self.assertTrue(any(e.where == "README.md" for e in r.evidence))
        self.assertTrue(claim_vs_diff(ISSUE, GOOD).passed)

    def test_claims_tests_but_no_test_files_changed(self):
        r = claim_vs_diff(ISSUE, CREEP)
        self.assertTrue(any("test" in e.detail.lower() for e in r.evidence))

    def test_missing_patch_gives_none_not_false(self):
        p = pr_with([FileChange("README.md", "modified", 0, 0, None)], "Removed the widgetc section.")
        r = claim_vs_diff(ISSUE, p)
        self.assertIsNone(r.passed)
        self.assertIn("patch not available", " ".join(e.detail for e in r.evidence))


if __name__ == "__main__":
    unittest.main()
