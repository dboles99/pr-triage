# Labelling rubric

Label each PR from the issue text, the PR's description and its diff, **before** looking at any
pr-triage output. Use `1` (yes), `0` (no) or `?` (cannot tell from what is visible). Write a short
note whenever the answer is not obvious.

## addresses_issue

Does the change itself (not the description) do what the issue asks?

- `1`: the diff makes the requested change, even if imperfectly (for example, it fixes the install
  command the issue names).
- `0`: the diff does something else, only describes a solution (a solution document, a proposal),
  or is empty or placeholder.
- `?`: the request is ambiguous, or the diff is not visible (too large, deleted fork).

## scope_creep

Does the PR change files or behaviour the issue did not ask for?

- `1`: unrelated files or edits (tool config such as `.aider*` in `.gitignore`, lockfiles, workflow
  changes, mass reformatting).
- `0`: every change serves the issue; small necessary companions (a test for the fix) count as in scope.

## unsupported_claims

Does the description claim something the diff does not show?

- `1`: for example "removed X" while X is still there, "added tests" with no test changes, "fixes #N"
  with no relevant change.
- `0`: the claims match the diff, or it makes no specific claims.

Labels made by the assistant are marked `labeller=assistant`. The owner spot-checks a random sample
of 20 (`pr-triage label sample --n 20`), and the agreement rate is reported in the study.
