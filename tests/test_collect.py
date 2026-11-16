import json
import tempfile
import unittest
from pathlib import Path

from pr_triage.collect import collect, linked_prs
from pr_triage.github import GitHub, RateLimited
from tests.fakes import FakeGitHub

R = "acme/widget"


def xref(num, repo=R, pr=True):
    src = {"number": num, "repository": {"full_name": repo}}
    if pr:
        src["pull_request"] = {"url": "x"}
    return {"event": "cross-referenced", "source": {"type": "issue", "issue": src}}


def pr_routes(n, head_repo=R, title="t"):
    detail = {"number": n, "html_url": f"https://github.com/{R}/pull/{n}", "user": {"login": f"u{n}"}, "title": title,
              "body": "Fixes #1", "state": "open", "merged": False, "merged_at": None, "created_at": "2026-11-02T00:00:00Z",
              "head": {"sha": f"s{n}", "repo": ({"full_name": head_repo} if head_repo else None)}}
    return {
        f"repos/{R}/pulls/{n}": (200, {}, detail),
        f"repos/{R}/pulls/{n}/files?per_page=100": (200, {}, [{"filename": "README.md", "status": "modified", "additions": 1, "deletions": 1, "patch": "+a"}]),
        f"repos/{R}/issues/{n}/comments?per_page=100": (200, {}, []),
        f"repos/{R}/pulls/{n}/reviews?per_page=100": (200, {}, []),
        f"repos/{R}/commits/s{n}/check-runs?per_page=100": (200, {}, {"check_runs": []}),
        f"repos/{R}/issues/{n}": (200, {}, {"reactions": {"total_count": 2}}),
    }


def base_routes(timeline):
    return {
        f"repos/{R}/issues/1": (200, {}, {"number": 1, "html_url": f"https://github.com/{R}/issues/1", "title": "Fix 🚀",
                                         "body": "x", "labels": [{"name": "bounty"}], "created_at": "2026-11-01T00:00:00Z"}),
        f"repos/{R}/issues/1/comments?per_page=100": (200, {}, [{"user": {"login": "lin"}, "body": "我来处理", "created_at": "t"}]),
        f"repos/{R}/issues/1/timeline?per_page=100": (200, {}, timeline),
    }


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "snap.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_linked_prs_uses_cross_referenced_pull_requests(self):
        tl = [xref(11), xref(12), xref(5, pr=False), {"event": "referenced", "commit_id": "abc"}]
        gh = GitHub(opener=FakeGitHub(base_routes(tl)))
        self.assertEqual(linked_prs(gh, R, 1), [(R, 11), (R, 12)])

    def test_pagination_follows_link_header(self):
        routes = {
            "repos/acme/widget/issues/1/comments?per_page=100": (200, {"Link": '<https://api.github.com/repos/acme/widget/issues/1/comments?per_page=100&page=2>; rel="next"'}, [{"id": 1}]),
            "repos/acme/widget/issues/1/comments?per_page=100&page=2": (200, {}, [{"id": 2}]),
        }
        gh = GitHub(opener=FakeGitHub(routes))
        self.assertEqual([c["id"] for c in gh.get("repos/acme/widget/issues/1/comments?per_page=100")], [1, 2])

    def test_rate_limit_writes_partial_and_raises(self):
        routes = {**base_routes([xref(11), xref(12)]), **pr_routes(11)}
        routes[f"repos/{R}/pulls/12"] = (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1794790000"}, {"message": "rate limit"})
        gh = GitHub(opener=FakeGitHub(routes))
        with self.assertRaises(RateLimited) as e:
            collect(R, 1, gh, self.out)
        self.assertTrue(e.exception.reset_at)
        snap = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertFalse(snap["complete"])
        self.assertEqual([p["number"] for p in snap["prs"]], [11])

    def test_resume_skips_collected_prs(self):
        routes = {**base_routes([xref(11), xref(12)]), **pr_routes(11)}
        routes[f"repos/{R}/pulls/12"] = (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1"}, {})
        with self.assertRaises(RateLimited):
            collect(R, 1, GitHub(opener=FakeGitHub(routes)), self.out)
        routes.update(pr_routes(12))
        fake = FakeGitHub(routes)
        snap = collect(R, 1, GitHub(opener=fake), self.out)
        self.assertTrue(snap["complete"])
        self.assertEqual(sorted(p["number"] for p in snap["prs"]), [11, 12])
        self.assertNotIn(f"repos/{R}/pulls/11", fake.calls)

    def test_deleted_head_fork_marks_unavailable(self):
        routes = {**base_routes([xref(11)]), **pr_routes(11, head_repo=None)}
        snap = collect(R, 1, GitHub(opener=FakeGitHub(routes)), self.out)
        self.assertTrue(snap["complete"])
        self.assertFalse(snap["prs"][0]["head_available"])

    def test_forbidden_check_runs_do_not_stop_collection(self):
        routes = {**base_routes([xref(11)]), **pr_routes(11)}
        routes[f"repos/{R}/commits/s11/check-runs?per_page=100"] = (403, {"x-ratelimit-remaining": "4999"}, {"message": "Resource not accessible by integration"})
        snap = collect(R, 1, GitHub(opener=FakeGitHub(routes)), self.out)
        self.assertTrue(snap["complete"])
        self.assertEqual(snap["prs"][0]["checks"], [])
        self.assertFalse(snap["prs"][0]["checks_available"])

    def test_utf8_body_with_cjk_and_emoji(self):
        routes = {**base_routes([xref(11)]), **pr_routes(11, title="修正 README ✅")}
        snap = collect(R, 1, GitHub(opener=FakeGitHub(routes)), self.out)
        self.assertEqual(snap["prs"][0]["title"], "修正 README ✅")
        self.assertIn("🚀", snap["issue"]["title"])
        self.assertEqual(snap["issue"]["comments"][0]["body"], "我来处理")
        self.assertEqual(len(snap["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()


class PathQuotingTests(unittest.TestCase):
    def test_non_ascii_path_is_quoted_and_never_raises(self):
        from pr_triage.github import file_text_at
        import base64
        quoted = "repos/acme/widget/contents/docs/%E6%97%A5%E6%9C%AC%E8%AA%9E.md?ref=s1"
        fake = FakeGitHub({quoted: (200, {}, {"encoding": "base64", "content": base64.b64encode("x".encode()).decode()})})
        self.assertEqual(file_text_at(GitHub(opener=fake), R, "docs/日本語.md", "s1"), "x")
        self.assertIsNone(file_text_at(GitHub(opener=FakeGitHub({})), R, "docs/日本語.md", "s1"))
