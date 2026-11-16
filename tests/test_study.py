import builtins
import copy
import json
import tempfile
import unittest
from pathlib import Path

from pr_triage import study

BASE = json.loads((Path(__file__).parent / "fixtures" / "snapshot_small.json").read_text(encoding="utf-8"))


def snap(repo, n, merged):
    s = copy.deepcopy(BASE)
    s["issue"].update(repo=repo, number=n, url=f"https://github.com/{repo}/issues/{n}")
    for p in s["prs"]:
        p["repo"] = repo
        p["merged"] = p["number"] in merged
    s["linked"] = [[repo, p["number"]] for p in s["prs"]]
    return s


SNAPS = {
    "acme/one#1": snap("acme/one", 1, {11}),
    "acme/multi#2": snap("acme/multi", 2, {11, 13}),
    "acme/open#3": snap("acme/open", 3, set()),
    "hanzo-go/lz4#1": snap("hanzo-go/lz4", 1, set()),
}


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.raw = self.dir / "raw"
        self.called = []

        def fake_collect(repo, n, out):
            self.called.append(f"{repo}#{n}")
            s = copy.deepcopy(SNAPS[f"{repo}#{n}"])
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
            return s

        self.manifest = study.build_dataset(list(SNAPS), self.raw, collect_fn=fake_collect)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lz4_issue_is_excluded(self):
        refs = [i["ref"] for i in self.manifest["issues"]]
        self.assertNotIn("hanzo-go/lz4#1", refs)
        self.assertNotIn("hanzo-go/lz4#1", self.called)
        self.assertIn("hanzo-go/lz4#1", [e["ref"] for e in self.manifest["exclusions"]])

    def test_outcome_classification(self):
        out = {i["ref"]: i["outcome"] for i in self.manifest["issues"]}
        self.assertEqual(out, {"acme/one#1": "one-merged", "acme/multi#2": "multi-merged", "acme/open#3": "open"})

    def test_manifest_has_no_bodies(self):
        res = study.run_study(self.manifest, self.raw, self.dir / "out", kai=None)
        published = json.dumps(self.manifest) + (self.dir / "out" / "features.csv").read_text(encoding="utf-8") + \
            json.dumps(json.loads((self.dir / "out" / "scores.json").read_text(encoding="utf-8")))

        def keys(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield k
                    yield from keys(v)
            elif isinstance(o, list):
                for v in o:
                    yield from keys(v)
        self.assertFalse({"body", "comments", "patch", "evidence"} & set(keys(self.manifest)))
        self.assertNotIn("Removed the widgetc section", published)
        self.assertNotIn("我来处理", published)
        self.assertIn("metrics", res)

    def test_replay_matches_fresh_run_on_fixture(self):
        study.run_study(self.manifest, self.raw, self.dir / "a", kai=None)
        study.run_study(self.manifest, self.raw, self.dir / "b", kai=None)
        self.assertEqual((self.dir / "a" / "scores.json").read_text(encoding="utf-8"), (self.dir / "b" / "scores.json").read_text(encoding="utf-8"))

    def test_drift_reported_for_changed_hash(self):
        def refetch(repo, n, out):
            s = copy.deepcopy(SNAPS[f"{repo}#{n}"])
            if repo == "acme/one":
                s["prs"][0]["title"] = "edited after the snapshot"
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
            return s
        study.run_study(self.manifest, None, self.dir / "c", kai=None, refetch_fn=refetch)
        drift = json.loads((self.dir / "c" / "drift.json").read_text(encoding="utf-8"))
        self.assertEqual([d["ref"] for d in drift["changed"]], ["acme/one#11"])

    def test_report_without_matplotlib_still_written(self):
        real = builtins.__import__

        def no_mpl(name, *a, **k):
            if name.startswith("matplotlib"):
                raise ImportError("no matplotlib")
            return real(name, *a, **k)
        builtins.__import__ = no_mpl
        try:
            study.run_study(self.manifest, self.raw, self.dir / "d", kai=None)
        finally:
            builtins.__import__ = real
        report = (self.dir / "d" / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("## Results", report)
        self.assertIn("figures not generated", report)

    def test_labels_produce_calibration_file(self):
        from pr_triage.label import label_rows, write_labels
        rows = [dict(r, addresses_issue="1" if r["pr"] == 11 else "0", scope_creep="0", unsupported_claims="0")
                for r in label_rows(sorted(self.raw.glob("acme__*.json")))]
        write_labels(rows, self.dir / "labels.csv", labeller="assistant")
        study.run_study(self.manifest, self.raw, self.dir / "f", kai=None, labels_csv=self.dir / "labels.csv")
        calib = json.loads((self.dir / "f" / "calibration.json").read_text(encoding="utf-8"))
        self.assertIn("touches_target", calib["checks"])

    def test_report_includes_diagnosis_with_labels(self):
        from pr_triage.label import label_rows, write_labels
        rows = [dict(r, addresses_issue="1" if r["pr"] in (11, 13) else "0", scope_creep="1" if r["pr"] == 13 else "0",
                     unsupported_claims="1" if r["pr"] == 13 else "0") for r in label_rows(sorted(self.raw.glob("acme__*.json")))]
        write_labels(rows, self.dir / "labels.csv", labeller="assistant")
        res = study.run_study(self.manifest, self.raw, self.dir / "g", kai=None, labels_csv=self.dir / "labels.csv",
                              label_note="Labels by an assistant; owner spot-check agreed on 59/60 labels.")
        d = res["metrics"]["diagnosis"]
        self.assertIn("label_ranker", d)
        self.assertEqual(d["acceptable_among_merged"], [1, 1])
        self.assertIn("touches_target", d["pass_rates"])
        self.assertIn("never_fail", d)
        report = (self.dir / "g" / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("## Diagnosis", report)
        self.assertIn("59/60", report)

    def test_tool_and_random_equal_when_all_scores_tie(self):
        flat = {"version": "flat", "weights": {}}  # no check counts: every PR scores 0
        res = study.run_study(self.manifest, self.raw, self.dir / "h", kai=None, weights=flat)
        m = res["metrics"]
        self.assertAlmostEqual(m["tool"]["mrr"], m["baselines"]["random"]["mrr"])
        self.assertAlmostEqual(m["tool"]["top1"], m["baselines"]["random"]["top1"])

    def test_metrics_use_only_one_merged_issues(self):
        res = study.run_study(self.manifest, self.raw, self.dir / "e", kai=None)
        self.assertEqual(res["metrics"]["tool"]["n_issues"], 1)
        self.assertIn("earliest", res["metrics"]["baselines"])


if __name__ == "__main__":
    unittest.main()
