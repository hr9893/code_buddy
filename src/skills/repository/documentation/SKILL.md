---
name: documentation_skill
description: Create or update documentation in the repository, including README files, API docs, usage guides, setup instructions, code comments, docstrings, and other technical docs. Use this skill for any GitHub issue about missing, outdated, unclear, or incorrect documentation, or one that asks to explain, describe, or document how something works, even if the issue never uses the word "docs".
---

# Documentation

Make the documentation accurate, clear, and consistent with the existing docs, and verify every claim against the actual code before writing it down.

## Workflow

1. Read the issue fully: what is missing or wrong, who the reader is, and which file or feature it concerns. Note anything ambiguous instead of guessing.
2. Find the relevant existing docs (README, `docs/`, docstrings, comments, changelog) and read their structure, tone, heading style, and formatting conventions.
3. Read the code being documented, and treat it as the source of truth for behavior, parameters, defaults, commands, and file paths.
4. Create a branch named `codepilot/<issue_number>-<short-slug>` from the default branch.
5. Write or edit the documentation to match the existing style, keeping the change focused on what the issue asks for.
6. Verify what you wrote: run every command and code example you added, confirm referenced files, functions, and options exist, and check that links and anchors resolve.
7. Update related places that would become inconsistent, such as a table of contents, an index page, a cross-reference, or the changelog if the repository keeps one.
8. Run the documentation build, doctests, or markdown/lint checks if the repository configures them, and fix any errors you introduced.
9. Review `git diff` to confirm only documentation changes are present and no secrets or unrelated edits slipped in, then commit with the message `docs: <summary> (#<issue_number>)`.
10. Push only the `codepilot/*` branch and open a pull request titled `docs: <summary>`. The body states what was documented, how it was verified, and ends with `Fixes #<issue_number>`.
11. Report the PR URL and a 2-3 sentence summary of what changed and which files were touched.

## Forbidden Actions

- Pushing to `main` or `master`, force pushing (`-f`, `--force`, `+refspec`), or pushing any branch that does not start with `codepilot/`.
- Reading, printing, or committing secrets, and writing real keys, tokens, passwords, or internal URLs into docs. Use clear placeholders such as `<YOUR_API_KEY>` instead.
- Documenting behavior, options, parameters, or features that you have not verified in the code.
- Changing code logic, behavior, or signatures. Only comments, docstrings, and documentation files may change.
- Hand-editing generated documentation (for example an API reference built from docstrings). Edit the source docstring or template instead.
- Rewriting, reformatting, or reorganizing sections the issue did not ask about.
- Deleting existing content unless it is clearly outdated and removing it is part of the issue.
- Adding documentation tooling, build dependencies, or CI changes unless the issue asks for them.
- Copying text verbatim from third-party sources, or editing license and legal files.
- Including commands, code samples, or links that you have not run or checked.
- Claiming the docs build or checks passed without running them.

## Edge Cases

- **Docs and code disagree:** trust the code, update the docs, and mention the mismatch in the PR. If the code itself looks wrong, report it in the PR instead of changing it.
- **Issue does not say which doc to change:** pick the most natural location following the existing structure, and say why in the PR.
- **Generated or versioned docs:** change the source or the correct version folder, and list any steps needed to regenerate.
- **Multiple languages or translations:** update the primary language, and note in the PR which translations are now out of date.
- **Feature cannot be verified or run in the sandbox:** document only what the code clearly shows, and say what could not be checked.

## Definition of Done

- The documentation matches the actual behavior of the code.
- Commands, code examples, and links were verified, and checks or the docs build pass if configured.
- Style and structure are consistent with the surrounding docs, and related references are updated.
- A PR from a `codepilot/*` branch is open and references the issue with `Fixes #<issue_number>`.