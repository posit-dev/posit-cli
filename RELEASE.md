# Releasing

The git tag is the only source of the version. `pyproject.toml` has no `version` field —
`hatch-vcs` reads the tag at build time. Do not add one.

Follow these steps to publish a new version to PyPI:

1. Make sure `main` holds everything you want in the release.
2. Tag the commit on `main` as `vX.Y.Z`.
3. Push the tag. This triggers `.github/workflows/release.yaml`.

```console
git checkout main && git pull
git tag v0.2.0
git push origin v0.2.0
```

The release workflow confirms that the build picked the tag up and that the tag is on `main`,
builds the wheel and sdist, smoke-tests the wheel, then publishes to PyPI through GitHub's OIDC
trusted-publisher flow. No PyPI token is stored in this repo. After PyPI accepts the upload, a
second job creates a GitHub release for the tag, with generated notes and the built artifacts
attached.

Run `just version` to see the version that a build gets from the current git state. A commit
after the last tag gets a development version (for example `0.2.1.dev3+g1a2b3c4`), which PyPI
rejects. Only a clean, tagged commit produces a release version.

## One-time setup for a new repo

- Create a `release` environment under the repo's Settings > Environments, with required
  reviewers. The `publish` job runs under this environment; without required reviewers, any tag
  push publishes to PyPI immediately with no human gate.
- Configure a trusted publisher for `posit-cli` on PyPI with: Owner `posit-dev`, Repository name
  `posit-cli`, Workflow name `release.yaml`, Environment name `release`.
