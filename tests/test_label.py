import csv
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from pr_triage.label import COLUMNS, label_rows, spot_check_sample, write_labels

FIX = Path(__file__).parent / "fixtures" / "snapshot_small.json"


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_has_no_score_columns(self):
        rows = label_rows([FIX])
        self.assertEqual(len(rows), 3)
        self.assertFalse(any(k in r for r in rows for k in ("score", "rank", "checks", "passed")))
        write_labels(rows, self.dir / "l.csv", labeller="assistant")
        header = (self.dir / "l.csv").read_text(encoding="utf-8").splitlines()[0].split(",")
        self.assertEqual(header, COLUMNS)

    def test_sample_is_reproducible_with_seed(self):
        rows = [{"issue": "a#1", "pr": i, "url": "", "title": "t", "files_changed": ""} for i in range(50)]
        write_labels(rows, self.dir / "l.csv", labeller="assistant")
        a = spot_check_sample(self.dir / "l.csv", n=20, seed=0)
        b = spot_check_sample(self.dir / "l.csv", n=20, seed=0)
        self.assertEqual([r["pr"] for r in a], [r["pr"] for r in b])
        self.assertEqual(len(a), 20)
        self.assertNotEqual([r["pr"] for r in a], [r["pr"] for r in spot_check_sample(self.dir / "l.csv", n=20, seed=1)])

    def test_labeller_and_date_recorded(self):
        write_labels(label_rows([FIX]), self.dir / "l.csv", labeller="assistant")
        with (self.dir / "l.csv").open(encoding="utf-8", newline="") as f:
            row = next(csv.DictReader(f))
        self.assertEqual(row["labeller"], "assistant")
        self.assertEqual(row["labelled_at"], dt.date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
