import unittest

from pr_triage.criteria import extract_criteria
from pr_triage.model import Criterion, Issue


def issue(body):
    return Issue(repo="acme/widget", number=1, url="", title="t", body=body)


class CriteriaTests(unittest.TestCase):
    def test_checklist_under_acceptance_criteria_heading(self):
        body = "## Summary\nx\n\n## Acceptance criteria\n- [ ] one\n- [x] two\n- [ ] three\n\n## Notes\n- not a criterion\n"
        self.assertEqual([c.text for c in extract_criteria(issue(body))], ["one", "two", "three"])

    def test_backticked_grep_becomes_absent_rule(self):
        body = ("## Acceptance criteria\n- [ ] `grep -n pierrec README.md` matches only credit lines\n"
                "- [ ] README must not contain `lz4c`\n")
        cs = extract_criteria(issue(body))
        self.assertEqual(cs[0].kind, "free_text")
        self.assertEqual(cs[1], Criterion(text="README must not contain `lz4c`", kind="absent", target="README.md", value="lz4c"))

    def test_contains_rule(self):
        cs = extract_criteria(issue("## Acceptance criteria\n- [ ] README.md must contain `go get acme.dev/widget`\n"))
        self.assertEqual((cs[0].kind, cs[0].target, cs[0].value), ("contains", "README.md", "go get acme.dev/widget"))

    def test_links_return_200_becomes_link_ok(self):
        cs = extract_criteria(issue("## Acceptance criteria\n- [ ] Every badge and link in the README returns 200.\n"))
        self.assertEqual((cs[0].kind, cs[0].target), ("link_ok", "README.md"))

    def test_what_to_do_bullets_used_when_no_criteria_heading(self):
        body = "## What to do\n- Change the install line.\n- Remove the CLI block.\n"
        self.assertEqual(len(extract_criteria(issue(body))), 2)

    def test_no_criteria_section_returns_empty(self):
        self.assertEqual(extract_criteria(issue("Please fix the README, thanks.")), [])


if __name__ == "__main__":
    unittest.main()
