---
name: bug_fix_skill
description: Fix an existing bug, exception, incorrect behavior, regression, or configuration problem in the repository. Use this skill for any GitHub issue reporting that something is broken, crashing, returning wrong results, or behaving differently than documented or expected, even if the issue never uses the word "bug".
---

# Bug Fix

Find the root cause of the reported problem, fix it with the smallest safe change, prove it with a test, and open a pull request that links the issue.

## Workflow

1. Read the issue fully: expected vs actual behavior, error messages, stack traces, reproduction steps, affected versions. Note anything ambiguous instead of guessing.
2. Locate the code from the stack trace or symptom, and read only the files involved in the failing path.
3. Reproduce the bug first, with an existing failing test or a minimal new test or script, before changing any code.
4. Identify the root cause where the problem originates, not where it surfaces, and state it in one sentence.
5. Create a branch named `codepilot/<issue_number>-<short-slug>` from the default branch.
6. Make the smallest fix that addresses the root cause, following the existing code style and patterns.
7. Add or update a regression test that fails without the fix and passes with it.
8. Run the related tests, then the project's full test command, plus linters or type checks if the repository configures them.
9. If tests fail, diagnose and retry within the retry limit. If they still fail, stop and report what failed instead of widening the change.
10. Review `git diff` for unrelated edits or secrets, then commit with the message `fix: <summary> (#<issue_number>)`.
11. Push only the `codepilot/*` branch and open a pull request titled `fix: <summary>`. The body states the bug, the root cause, the fix, the tests added and run, and ends with `Fixes #<issue_number>`.
12. Report the PR URL and a 2-3 sentence summary of what changed and which files were touched.

## Forbidden Actions

- Pushing to `main` or `master`, force pushing (`-f`, `--force`, `+refspec`), or pushing any branch that does not start with `codepilot/`.
- Reading, printing, or committing secrets such as `.env` files, private keys, tokens, or credentials.
- Unrelated refactors, renames, formatting sweeps, or drive-by fixes outside the reported issue.
- Deleting, skipping, or weakening existing tests (`skip`, `xfail`, loosened assertions) to get a green run.
- Special-casing the failing input or hard-coding expected values to satisfy a test.
- Silencing errors (bare `except`, swallowed exceptions, ignored return codes) instead of fixing the cause.
- Adding, removing, or upgrading dependencies unless the bug is caused by that dependency.
- Editing CI/CD configuration, lockfiles, or build files unless the issue is about them.
- Claiming tests passed without running them, or opening a PR with failing tests without saying so.
- Guessing at a fix when the issue is too ambiguous to fix safely; report what is missing instead.

## Edge Cases

- **Cannot reproduce:** report the exact steps tried and the environment, and do not open a PR with a speculative fix.
- **Several bugs in one issue:** fix the primary one, and mention the others in the PR description instead of fixing them.
- **Flaky or already-failing tests:** note which tests failed before the change so reviewers can tell them apart from regressions.
- **Fix needs a behavior or API change:** keep it as small as possible and call it out explicitly in the PR description.

## Definition of Done

- The bug is reproduced before the fix and verified fixed after it.
- A regression test covers the root cause.
- The relevant tests, and the full suite where practical, pass.
- A PR from a `codepilot/*` branch is open and references the issue with `Fixes #<issue_number>`.