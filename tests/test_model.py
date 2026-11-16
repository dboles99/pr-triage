import unittest
from pathlib import Path

from pr_triage.model import FileChange, Issue, PR, load_snapshot

FIX = Path(__file__).parent / "fixtures" / "snapshot_small.json"


class ModelTests(unittest.TestCase):
    def test_load_snapshot_round_trips_unicode(self):
        issue, prs = load_snapshot(FIX)
        self.assertIsInstance(issue, Issue)
        self.assertIn("🚀", issue.title)
        self.assertEqual(issue.comments[0]["body"], "我来处理这个问题。")

    def test_missing_patch_is_none(self):
        _, prs = load_snapshot(FIX)
        logo = next(f for f in prs[2].files if f.path == "assets/logo.png")
        self.assertIsNone(logo.patch)

    def test_pr_count_and_types(self):
        _, prs = load_snapshot(FIX)
        self.assertEqual(len(prs), 3)
        self.assertTrue(all(isinstance(p, PR) for p in prs))
        self.assertTrue(all(isinstance(f, FileChange) for p in prs for f in p.files))
        self.assertFalse(prs[2].head_available)


if __name__ == "__main__":
    unittest.main()
