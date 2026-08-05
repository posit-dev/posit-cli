# Releasing

Follow these steps to publish a new version to PyPI:

1. Bump `version` in `pyproject.toml`.
2. Run `uv lock` if the bump changed any dependency. CI fails the build if `uv.lock` has drifted.
3. Commit the change and merge it to `main`.
4. Tag the merged commit on `main` as `vX.Y.Z`. The tag must match the `pyproject.toml` version
   exactly.
5. Push the tag. This triggers `.github/workflows/release.yaml`.

The release workflow checks the tag against `pyproject.toml` and against `main`, builds the
wheel and sdist, smoke-tests the wheel, then publishes to PyPI through GitHub's OIDC
trusted-publisher flow. No PyPI token is stored in this repo.

## One-time setup for a new repo

- Create a `release` environment under the repo's Settings > Environments, with required
  reviewers. The `publish` job runs under this environment; without required reviewers, any tag
  push publishes to PyPI immediately with no human gate.
- Configure a trusted publisher for `posit-cli` on PyPI with: Owner `posit-dev`, Repository name
  `posit-cli`, Workflow name `release.yaml`, Environment name `release`.
