# Plan: publish posit-cli to PyPI

## Goal

Add CI steps that build and publish `posit-cli` to PyPI on a version tag,
following the pattern used by `posit-dev/posit-sdk-py` and
`posit-dev/rsconnect-python`. Both use:

- `astral-sh/setup-uv` + `uv build` for the build step.
- Trusted publishing (OIDC) via `pypa/gh-action-pypi-publish@release/v1`,
  no long-lived PyPI API token, `permissions: id-token: write`.
- A tag push (`v*.*.*` or bare `*`) as the release trigger.

## Blocker to resolve before the workflow can succeed (not blocking this PR)

**The name `posit-cli` is already registered on PyPI**, owned by an unrelated
project (`sol-eng/posit-cli` by SamEdwardes, latest release `0.1.1a1`).
This matters for two reasons, not just cosmetics:

1. `posit-dev` cannot pre-register a PyPI "pending publisher" for a name that
   already exists — pending publishers are only for names that don't exist
   yet.
2. `posit-dev` cannot add a trusted publisher to the *existing* `posit-cli`
   project unless granted collaborator access by its current owner.

So the release workflow below will be correct but **cannot actually publish**
until this is resolved (new name, or ownership/collaborator access on the
existing project). Per your call, proceeding with `posit-cli` as a
placeholder everywhere; you're handling the naming question separately.

## Gaps in the current build toolchain

Found by comparing this repo against posit-sdk-py and rsconnect-python. None
of these block writing the workflow files, but the workflow will expose them
(fail lint, fail build, etc.) if left unaddressed.

1. **No CI at all yet.** `.github/` doesn't exist in this repo. Both
   reference projects gate releases on a passing CI job; here the release
   workflow would be the *first* thing to run any lint/test/build step. I'm
   adding a basic `ci.yaml` (lint + test matrix + build) alongside the
   release workflow so tags aren't published untested.

2. **No LICENSE file on disk.** `pyproject.toml` declares
   `license = { text = "MIT" }`, but there is no `LICENSE` file in the repo.
   Both reference projects ship one (posit-sdk-py's `license = { file =
   "LICENSE" }` even points at it). PyPI renders license info from the file
   when present; worth adding for a real release.

3. **Static, hand-maintained version.** `pyproject.toml` hardcodes
   `version = "0.1.0"`. Neither reference project does this by hand:
   - posit-sdk-py uses `setuptools-scm` (`dynamic = ["version"]`, version
     derived from the git tag).
   - rsconnect-python keeps a static version too, but its release workflow
     *asserts* the pushed tag matches `uv version --short` and fails the
     release otherwise.
   posit-cli has neither: no dynamic versioning and no tag/version
   consistency check. I've modeled the release workflow on rsconnect-python's
   assertion approach (simplest change), but adding `hatch-vcs` for
   git-tag-driven versioning (this repo already uses hatchling) is the
   lower-maintenance option if you want it instead — flagging as a decision
   for you, not deciding it myself.

4. **No lint or type-check tooling declared.** Both reference projects run
   `ruff` (lint + format check) and a type checker (`pyright` for
   posit-sdk-py) in CI. This repo has no `ruff`/`pyright` in
   `[project.optional-dependencies]` or a `dependency-groups` table, and no
   `ruff.toml`/`[tool.ruff]` config. The `ci.yaml` I'm adding needs at least
   `ruff` to do anything meaningful — currently there's nothing to run.

5. **No task runner.** Both reference repos drive CI through a `Makefile`
   (posit-sdk-py) or `just` (rsconnect-python), so the workflow files stay
   thin and the same commands work locally. This repo has neither. I'm
   keeping the new workflow files self-contained (raw `uv run`/`uv build`
   commands) rather than introducing a new tool, but that means CI and local
   dev commands can drift — worth a `Makefile` later if this grows.

6. **Git-pinned rsconnect-python dependency.** `pyproject.toml` depends on
   `rsconnect-python @ git+https://github.com/posit-dev/rsconnect-python.git@main`
   (already called out as TEMPORARY in that file, tracking unreleased OAuth
   commands). A package published to PyPI with a direct git-URL dependency is
   unusual and fragile for consumers (`pip install posit-cli` will try to
   clone GitHub at install time). This should be pinned to a released
   rsconnect-python version before a real PyPI release, independent of the
   CI/publish plumbing itself.

7. **No `py.typed` marker.** Minor; only matters if you want the
   `Typing :: Typed` classifier posit-sdk-py carries. Not a blocker.

## Decisions (confirmed by you)

- Versioning: keep the static `version` field in `pyproject.toml`, and have
  the release workflow assert the pushed tag matches it (rsconnect-python
  style) rather than switching to `hatch-vcs`.
- Lint: add `ruff` now, not deferred to a follow-up.
- LICENSE: add an MIT `LICENSE` file now.
- Naming clash with PyPI's existing `posit-cli`: proceed using `posit-cli`
  everywhere; you're resolving the naming/ownership question separately.

## Implemented

- **`LICENSE`** — standard MIT text, copyright Posit Software, PBC.
  `pyproject.toml`'s `license` field now points at it
  (`{ file = "LICENSE" }`) instead of an inline string.
- **`pyproject.toml`** — added a `lint` extra (`ruff>=0.6`) and a
  `[tool.ruff]`/`[tool.ruff.lint]` config. Rule selection is pinned
  explicitly to ruff's own documented defaults (`E4`, `E7`, `E9`, `F`)
  rather than left implicit, so a future ruff upgrade can't silently turn on
  new default rules and break CI.
- **Pinned `rsconnect-python` to the latest release.** Changed the
  dependency from
  `rsconnect-python @ git+https://github.com/posit-dev/rsconnect-python.git@main`
  to `rsconnect-python>=1.30,<2`. The OAuth `login`/`logout` commands this
  repo was tracking on `main` for have since shipped in the `1.30.0`
  release, so the git dependency is no longer needed. Dropped the now-unused
  `[tool.hatch.metadata] allow-direct-references = true` (only needed for
  git dependencies). Simplified `src/posit_cli/connect/__init__.py`: it had
  an `if "login" in rsconnect_cli.commands` branch to handle the
  main-branch-only case; since the pin guarantees `login` is always present,
  that branch is now dead code and was removed, leaving just the one epilog
  string. Re-verified `tests/test_rsconnect_contract.py`'s internal-API
  assumptions against the real `1.30.0` release — still holds.
- **`Justfile`** — task runner recipes (`test`, `lint`, `fmt`, `build`,
  `install`, `version`, `clean`), modeled on rsconnect-python's `Justfile`.
  CI and the release workflow call these instead of raw `uv` commands, so
  the same commands work identically in CI and local dev.
  - Note: `version` recipe uses `@uv version --short` (the `@` suppresses
    just's default command-echo) — without it, `just version`'s output
    includes the echoed command line before the actual version string,
    which would break the release workflow's tag-match comparison.
- **`.github/workflows/ci.yaml`** — three jobs on PR + push to `main`:
  `lint` (`just lint`), `test` (`just test <version>` matrix, py3.9–3.13),
  `build` (`just build`). Uses `extractions/setup-just` alongside
  `astral-sh/setup-uv`.
- **`.github/workflows/release.yaml`** — on `v*.*.*` tag push: checkout,
  setup-uv, setup-just, assert the tag (minus its `v` prefix) matches
  `just version`, assert the tag is on `main`, `just build`, smoke-test the
  built wheel (`posit --help` from the wheel, no project install), publish
  via `pypa/gh-action-pypi-publish@release/v1` (trusted publishing,
  `permissions: id-token: write`, no stored PyPI token).
- Ran `ruff format` once to bring the two pre-existing files it flagged
  (`src/posit_cli/connect/api.py`, `tests/test_api.py`) in line with the new
  config — no behavior change, formatting only.
- Verified locally: `just lint` clean, full `just test` suite passes
  (64 tests) against the pinned `rsconnect-python==1.30.0`, `just build`
  succeeds, and the built wheel's `posit --help` smoke test (as used in
  `release.yaml`) works. Also confirmed the tag-match assertion logic
  (`tag="${GITHUB_REF_NAME#v}"` vs. `just version`) resolves correctly.

## Manual setup (outside this repo, can't be done via CI files)

- Register `posit-dev/posit-cli`'s `release.yaml` as a trusted publisher on
  PyPI for the `posit-cli` project — blocked until the naming/ownership
  question above is resolved.

## Still open / not addressed in this change

- **No `py.typed` marker** (gap #7 above) — minor, only matters for the
  `Typing :: Typed` classifier.
- **PyPI name clash** — see blocker section above; not resolved here.
