import csv
import json
import tempfile
import unittest
from pathlib import Path

from pr_triage import calibrate as cal


class CalibrateTests(unittest.TestCase):
    def test_binary_metrics_known_case(self):
        m = cal.binary_metrics([1, 1, 0, 0], [1, 0, 1, 0])
        self.assertEqual(m, {"accuracy": 0.5, "precision": 0.5, "recall": 0.5, "f1": 0.5, "n": 4})

    def test_brier_perfect_and_worst(self):
        self.assertEqual(cal.brier([1, 0], [1.0, 0.0]), 0.0)
        self.assertEqual(cal.brier([1, 0], [0.0, 1.0]), 1.0)

    def test_reliability_bins_counts_sum_to_n(self):
        p = [0.05, 0.15, 0.55, 0.95, 0.96, 1.0]
        rows = cal.reliability([0, 0, 1, 1, 1, 1], p, bins=10)
        self.assertEqual(sum(r["n"] for r in rows), len(p))
        top = [r for r in rows if r["bin_high"] == 1.0][0]
        self.assertEqual(top["n"], 3)

    def test_auc_none_for_single_class(self):
        self.assertIsNone(cal.auc([1, 1], [0.2, 0.9]))
        self.assertEqual(cal.auc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]), 0.75)

    def test_choose_threshold_picks_best_f1(self):
        t = cal.choose_threshold([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8])
        self.assertEqual(t["threshold"], 0.35)
        self.assertAlmostEqual(t["f1"], 0.8)
        self.assertEqual(len(t["table"]), 4)

    def test_rank_metrics_top1_and_mrr(self):
        self.assertEqual(cal.rank_metrics([[5, 6], [7, 8]], [5, 8]), {"top1": 0.5, "mrr": 0.75, "n_issues": 2})

    def test_baselines_orderings(self):
        issues = [{"ref": "a#1", "prs": [{"number": 1, "created_at": "2026-01-02", "changes": 50, "reactions": 0},
                                         {"number": 2, "created_at": "2026-01-01", "changes": 5, "reactions": 3}]}]
        b = cal.baselines(issues)
        self.assertEqual(b["earliest"], [[2, 1]])
        self.assertEqual(b["smallest_diff"], [[2, 1]])
        self.assertEqual(b["most_reactions"], [[2, 1]])
        self.assertEqual(sorted(b["random"][0]), [1, 2])

    def test_loio_never_sees_held_out_issue(self):
        features = {f"i{k}": {1: {"a": 1, "b": 0}, 2: {"a": 0, "b": 1}} for k in range(4)}
        truth = {f"i{k}": 1 for k in range(4)}
        seen = []
        real_fit = cal._fit

        def spy(feats, tr, grid):
            seen.append(set(feats))
            return real_fit(feats, tr, grid)

        cal._fit = spy
        try:
            res = cal.fit_weights_loio(features, truth)
        finally:
            cal._fit = real_fit
        folds = seen[:4]
        for k, keys in zip(sorted(features), folds):
            self.assertNotIn(k, keys)
        self.assertEqual(res["loio_mrr"], 1.0)
        self.assertGreater(res["weights"]["a"], res["weights"]["b"])

    def test_bootstrap_ci_brackets_mean(self):
        lo, hi = cal.bootstrap_ci([0, 1, 1, 0, 1, 1, 1, 0], n=500, seed=0)
        self.assertLess(lo, 0.625)
        self.assertGreater(hi, 0.625)

    def test_checks_pair_with_their_own_label_and_polarity(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            with (t / "labels.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["issue", "pr", "url", "addresses_issue", "scope_creep", "unsupported_claims", "labeller", "labelled_at", "notes"])
                w.writerow(["a#1", "1", "", "1", "0", "0", "assistant", "d", ""])
                w.writerow(["a#1", "2", "", "0", "1", "1", "assistant", "d", ""])
            # A perfect scope check passes the clean PR and fails the creeping one; a perfect claim check likewise.
            scores = {"a#1": {"1": {"scope_creep": {"value": 0, "passed": True}, "claim_vs_diff": {"value": 0, "passed": True}},
                              "2": {"scope_creep": {"value": 2, "passed": False}, "claim_vs_diff": {"value": 1, "passed": False}}}}
            (t / "scores.json").write_text(json.dumps(scores), encoding="utf-8")
            out = cal.calibrate_files(t / "labels.csv", t / "scores.json", t / "o")
            self.assertEqual(out["checks"]["scope_creep"]["scope_creep"]["accuracy"], 1.0)
            self.assertEqual(out["checks"]["claim_vs_diff"]["unsupported_claims"]["accuracy"], 1.0)
            self.assertNotIn("addresses_issue", out["checks"]["scope_creep"])  # no cross-pairing

    def test_calibrate_cli_writes_metrics(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            with (t / "labels.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["issue", "pr", "url", "addresses_issue", "scope_creep", "unsupported_claims", "labeller", "labelled_at", "notes"])
                w.writerow(["a#1", "1", "", "1", "0", "0", "assistant", "2026-11-16", ""])
                w.writerow(["a#1", "2", "", "0", "1", "1", "assistant", "2026-11-16", ""])
            scores = {"a#1": {"1": {"touches_target": {"value": 1, "passed": True}, "addresses_issue": {"value": 0.9, "passed": True}},
                              "2": {"touches_target": {"value": 0, "passed": False}, "addresses_issue": {"value": 0.2, "passed": False}}}}
            (t / "scores.json").write_text(json.dumps(scores), encoding="utf-8")
            from pr_triage.cli import main
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["calibrate", "--labels", str(t / "labels.csv"), "--scores", str(t / "scores.json"), "--out", str(t / "o")]), 0)
            out = json.loads((t / "o" / "calibration.json").read_text(encoding="utf-8"))
            self.assertEqual(out["checks"]["touches_target"]["addresses_issue"]["accuracy"], 1.0)
            self.assertEqual(out["models"]["addresses_issue"]["brier"], round((0.1 ** 2 + 0.2 ** 2) / 2, 4))


if __name__ == "__main__":
    unittest.main()


class TieTests(unittest.TestCase):
    def test_expected_rr_averages_over_ties(self):
        # truth tied with one other PR at the top: expected RR = (1/1 + 1/2) / 2
        self.assertAlmostEqual(cal.expected_rr({1: 0.5, 2: 0.5, 3: 0.1}, 1), 0.75)
        self.assertAlmostEqual(cal.expected_rr({1: 0.9, 2: 0.5}, 1), 1.0)
        self.assertAlmostEqual(cal.expected_rr({1: 0.1, 2: 0.5, 3: 0.5}, 1), 1 / 3)

    def test_random_baseline_is_analytic(self):
        # expected MRR of a random order over n PRs is H_n / n
        self.assertAlmostEqual(cal.random_mrr([2, 4]), ((1 + 1 / 2) / 2 + (1 + 1 / 2 + 1 / 3 + 1 / 4) / 4) / 2)

    def test_baselines_use_same_tie_rule_as_tool(self):
        issues = [{"ref": "a#1", "prs": [{"number": 1, "created_at": "2026-01-01", "changes": 5, "reactions": 0},
                                         {"number": 2, "created_at": "2026-01-02", "changes": 5, "reactions": 0}]}]
        m = cal.baseline_mrr(issues, {"a#1": 1})
        self.assertAlmostEqual(m["most_reactions"]["mrr"], 0.75)  # all tied: no free win for the lower number
        self.assertAlmostEqual(m["smallest_diff"]["mrr"], 0.75)
        self.assertAlmostEqual(m["earliest"]["mrr"], 1.0)
        self.assertAlmostEqual(m["random"]["mrr"], 0.75)
