---
name: dependency_update_skill
description: Update, upgrade, downgrade, pin, or replace a dependency, library, framework, runtime, or tool version in the repository. Use this skill for any GitHub issue about bumping a package version, fixing a vulnerable or deprecated dependency, resolving a version conflict, or migrating from one library to another, even if the issue only names the package and not the word "update".
---

# Dependency Update

Change the requested dependency to the requested version with the smallest possible footprint, adapt the code for any breaking changes, and prove the project still builds and passes its tests.

## Workflow

1. Read the issue fully: which package, current version, target version, and the reason (security advisory, deprecation, bug fix, new feature, conflict). If no target version is given, choose the latest stable release that is compatible with the project.
2. Find where the dependency is declared (`pyproject.toml`, `requirements*.txt`, `package.json`, `pom.xml`, `build.gradle`, `Cargo.toml`, `go.mod`, and so on) and which lockfile belongs to it.
3. Check how the package is used in the code, and read the release notes or changelog for breaking changes, deprecations, and removed APIs between the current and target versions.
4. Create a branch named `codepilot/<issue_number>-<short-slug>` from the default branch.
5. Update only the requested dependency in the manifest, then regenerate the lockfile with the project's own package manager command (for example `uv lock`, `npm install`, `poetry lock`, `mvn versions:use-dep-version`, `cargo update -p`).
6. Adapt the code for breaking changes and removed APIs, keeping edits limited to what the new version requires.
7. Run the build, the full test suite, and linters or type checks if the repository configures them.
8. If tests or the build fail, diagnose whether the cause is the new version or an existing failure, and retry within the retry limit. If it still fails, stop and report the incompatibility instead of forcing the update through.
9. Review `git diff` to confirm only the intended manifest, lockfile, and necessary code changes are present, then commit with the message `chore(deps): update <package> from <old> to <new> (#<issue_number>)`.
10. Push only the `codepilot/*` branch and open a pull request titled `chore(deps): update <package> to <new>`. The body lists old and new versions, the reason, breaking changes handled, tests run, and ends with `Fixes #<issue_number>`.
11. Report the PR URL and a 2-3 sentence summary of what changed and which files were touched.

## Forbidden Actions

- Pushing to `main` or `master`, force pushing (`-f`, `--force`, `+refspec`), or pushing any branch that does not start with `codepilot/`.
- Reading, printing, or committing secrets such as `.env` files, private keys, tokens, or registry credentials.
- Hand-editing lockfiles or checksums instead of regenerating them with the package manager.
- Updating unrelated dependencies, running a blanket "upgrade all", or letting the lockfile drift beyond what the requested change requires.
- Guessing a version number without confirming it exists, or switching to a package with a similar name without confirming it is the intended one.
- Adding new dependencies that the issue did not ask for.
- Bypassing resolution errors with flags such as `--force`, `--legacy-peer-deps`, or `--no-verify` without stating so in the PR.
- Jumping to a new major version when the issue asks for a patch or minor update, unless the issue explicitly requests it.
- Downgrading a dependency that carries a security fix, unless the issue explicitly asks for it.
- Deleting, skipping, or weakening tests, or pinning old behavior to hide breakage caused by the update.
- Committing installed dependency folders or build output (`node_modules`, `.venv`, `target`, `dist`).
- Editing CI/CD configuration or unrelated build settings unless the update itself requires it.
- Claiming the build or tests passed without running them.

## Edge Cases

- **Security advisory:** include the advisory ID and the first fixed version in the PR, and prefer the minimum version that resolves it.
- **Version conflict with another dependency:** report the conflicting package and constraint, and only widen or change other constraints if the issue allows it.
- **Library replacement:** migrate each usage of the old library, remove the old dependency, and list every touched call site in the PR.
- **Several manifests or a monorepo:** update every place the package is declared so versions stay consistent, and list them in the PR.
- **No tests exist:** at minimum build or import the project and run a smoke check, and say clearly in the PR how it was verified.
- **Target version does not exist or is yanked:** stop and report it instead of picking a different version silently.

## Definition of Done

- The dependency is at the requested version in the manifest and the regenerated lockfile.
- The project builds and its tests pass, or any pre-existing failures are called out.
- Breaking changes are handled with minimal code edits.
- A PR from a `codepilot/*` branch is open and references the issue with `Fixes #<issue_number>`.