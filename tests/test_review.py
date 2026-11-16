import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pr_triage.cli import main
from pr_triage.model import CheckResult
from pr_triage.score import score

FIX = Path(__file__).parent / "fixtures" / "snapshot_small.json"


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def run_review(self, snapshot=FIX):
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["review", "acme/widget#1", "--snapshot", str(snapshot), "--out", str(self.out), "--no-kai", "--offline"])
        self.assertEqual(code, 0)
        return (self.out / "report.md").read_text(encoding="utf-8"), json.loads((self.out / "report.json").read_text(encoding="utf-8"))

    def test_review_ranks_readme_change_first(self):
        _, js = self.run_review()
        order = [r["number"] for r in js["ranking"]]
        self.assertEqual(order[0], 11)
        self.assertEqual(order[-1], 12)

    def test_report_lists_checks_not_run(self):
        md, js = self.run_review()
        self.assertIn("model checks: not run", md)
        self.assertIn("injection", js["meta"]["checks_not_run"])

    def test_report_states_no_criteria_found(self):
        d = json.loads(FIX.read_text(encoding="utf-8"))
        d["issue"]["body"] = "Please fix the README install command in README.md, thanks."
        p = Path(self.tmp.name) / "nocrit.json"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        md, js = self.run_review(p)
        self.assertIn("no acceptance criteria found", md.lower())
        self.assertEqual(js["ranking"][0]["number"], 11)

    def test_report_md_and_json_written_utf8(self):
        md, js = self.run_review()
        self.assertIn("🚀", md)
        self.assertIn("🚀", js["issue"]["title"])

    def test_json_mirrors_ranking(self):
        md, js = self.run_review()
        for r in js["ranking"]:
            self.assertIn(f"#{r['number']}", md)
            self.assertIn(r["ref"], set(js["checks"]))

    def test_none_results_do_not_count_against(self):
        w = {"a": 1.0, "b": 1.0}
        self.assertEqual(score([CheckResult("a", "deterministic", 1, True), CheckResult("b", "deterministic", None, None)], w), 1.0)
        self.assertEqual(score([CheckResult("a", "deterministic", 0, False), CheckResult("b", "deterministic", 1, True)], w), 0.5)


if __name__ == "__main__":
    unittest.main()


class WeightTests(unittest.TestCase):
    def test_unvalidated_model_checks_carry_no_weight(self):
        from pr_triage.score import load_weights
        w = load_weights()["weights"]
        self.assertEqual((w["injection"], w["addresses_issue"], w["effort"]), (0.0, 0.0, 0.0))


class CrossRepoTests(unittest.TestCase):
    def test_same_number_in_two_repos_are_distinct(self):
        import dataclasses
        from pr_triage.model import load_snapshot
        from pr_triage.score import run_checks, score, load_weights
        from pr_triage.report import render
        issue, prs = load_snapshot(FIX)
        other = dataclasses.replace(prs[0], repo="acme/other", url="https://github.com/acme/other/pull/11")
        both = [prs[0], other]
        res = run_checks(issue, both, None, None)
        self.assertEqual(len(res), 2)
        w = load_weights()
        md, js = render(issue, both, res, {k: score(v, w["weights"]) for k, v in res.items()}, {"weights": w["weights"]})
        self.assertEqual(len(js["ranking"]), 2)
        self.assertIn("acme/other#11", md)


class MinorReviewTests(unittest.TestCase):
    def test_link_check_refuses_private_addresses(self):
        from unittest import mock
        from pr_triage import cli
        class Ok:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass
        with mock.patch.object(cli.urllib.request, "urlopen", return_value=Ok()) as op:
            for url in ("http://127.0.0.1/x", "http://localhost:8080/", "http://169.254.169.254/latest", "http://10.1.2.3/"):
                self.assertEqual(cli._head_status(url), 0, url)
            self.assertEqual(op.call_count, 0)

    def test_report_lists_free_text_criteria(self):
        d = json.loads(FIX.read_text(encoding="utf-8"))
        d["issue"]["body"] += "\n- [ ] The README reads naturally for new users\n"
        d["issue"]["body"] = d["issue"]["body"].replace("Points: 75 (reputation, not money)", "")
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "s.json"
            p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                main(["review", "acme/widget#1", "--snapshot", str(p), "--out", str(Path(t) / "o"), "--no-kai", "--offline"])
            md = (Path(t) / "o" / "report.md").read_text(encoding="utf-8")
        self.assertIn("The README reads naturally for new users", md)
