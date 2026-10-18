---
name: feature_addition_skill
description: Add new functionality to the repository, such as a new endpoint, command, option, capability, integration, or workflow that does not exist yet. Use this skill for any GitHub issue that asks to add, support, implement, or introduce something new, even if the issue is phrased as a request or enhancement and never uses the word "feature".
---

# Feature Addition

Implement exactly the requested capability, fit it into the existing architecture and conventions, cover it with tests, and open a pull request that links the issue.

## Workflow

1. Read the issue fully and extract the requirements and acceptance criteria. If the request is too ambiguous to implement safely, report what is missing instead of guessing.
2. Explore the codebase to find where the feature belongs, and study how similar features are structured, named, configured, and tested.
3. Choose the smallest design that satisfies the requirements and follows the existing architecture, reusing existing helpers and patterns.
4. Create a branch named `codepilot/<issue_number>-<short-slug>` from the default branch.
5. Implement the feature in small, coherent steps, with input validation and error handling that match the surrounding code.
6. Keep existing behavior and public interfaces backward compatible, and use the project's settings or configuration mechanism instead of hard-coded values.
7. Add tests covering the main behavior, edge cases, and failure paths of the new feature.
8. Update user-facing documentation, usage examples, or configuration samples if the feature changes how the project is used.
9. Run the related tests, then the full test suite, plus linters or type checks if the repository configures them.
10. If tests fail, diagnose and retry within the retry limit. If they still fail, stop and report what failed instead of widening the change.
11. Review `git diff` to remove debug output, dead code, and unrelated edits, then commit with the message `feat: <summary> (#<issue_number>)`.
12. Push only the `codepilot/*` branch and open a pull request titled `feat: <summary>`. The body states what was added, the design choices, the tests added and run, any docs updated, and ends with `Fixes #<issue_number>`.
13. Report the PR URL and a 2-3 sentence summary of what changed and which files were touched.

## Forbidden Actions

- Pushing to `main` or `master`, force pushing (`-f`, `--force`, `+refspec`), or pushing any branch that does not start with `codepilot/`.
- Reading, printing, or committing secrets such as `.env` files, private keys, tokens, or credentials, or hard-coding secrets and environment-specific values in the code.
- Adding extra features, options, or behavior beyond what the issue asks for.
- Unrelated refactors, renames, or formatting sweeps outside the code the feature needs to touch.
- Changing or removing existing public behavior, APIs, or defaults unless the issue explicitly requires it.
- Adding new dependencies unless the feature cannot reasonably be built without them, and then only with the reason stated in the PR.
- Deleting, skipping, or weakening existing tests, or shipping the feature without tests of its own.
- Editing CI/CD configuration, lockfiles, or build files unless the feature requires it.
- Leaving behind debug prints, commented-out code, or unresolved TODOs.
- Claiming tests passed without running them, or opening a PR with failing tests without saying so.
- Guessing at requirements when the issue is too ambiguous to implement safely; report what is missing instead.

## Edge Cases

- **Ambiguous or incomplete requirements:** state the assumptions you made in the PR, or stop and report the missing details if the risk is high.
- **Feature is too large for one change:** implement the smallest useful slice that satisfies the core request, and list the follow-up work in the PR description.
- **Feature already partly exists:** extend the existing code instead of duplicating it, and point out the overlap in the PR.
- **Needs a breaking change:** keep the break as small as possible, make it explicit in the PR, and keep a compatible path if one is feasible.
- **Repository uses feature flags or config switches:** follow that convention so the feature can be turned off.
- **No test setup exists:** add the smallest practical test, or describe in the PR how the feature was verified manually.

## Definition of Done

- The requested capability works as described in the issue and meets its acceptance criteria.
- New tests cover the main behavior and edge cases, and the relevant tests, and the full suite where practical, pass.
- Existing behavior is unchanged, and any user-facing docs or examples are updated.
- A PR from a `codepilot/*` branch is open and references the issue with `Fixes #<issue_number>`.