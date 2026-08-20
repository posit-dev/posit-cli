# Contributing

This guide covers local development for `posit-cli`. End-user installation and CLI usage are documented in [README.md](README.md).

## Prerequisites

Install these tools before starting:

- Git
- Python 3.8 or newer
- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just)

The project uses uv for dependency management and virtual environments. The supported Python versions are 3.8 through 3.14, which are tested in CI.

## Set Up

Clone the repository and change into its directory:

```console
git clone https://github.com/posit-dev/posit-cli.git
cd posit-cli
```

Sync the project, test, and lint dependencies:

```console
just deps
```

This runs `uv sync --all-extras`, using `uv.lock` to create or update the project environment in `.venv`. You do not need to activate `.venv` when using the `just` recipes.

To put an editable `posit` command on your `PATH`, run:

```console
just dev
posit --help
```

`just dev` installs the checkout as an editable uv tool. Changes to the source are therefore available through `posit` without rebuilding or reinstalling the package. If the command is not found, add the directory printed by `uv tool dir --bin` to your `PATH`, or run `uv tool update-shell`.

## Common Commands

Run these commands from the repository root:

| Command | Purpose |
| --- | --- |
| `just deps` | Sync runtime, test, and lint dependencies from `uv.lock`. |
| `just dev` | Install the checkout as an editable uv tool. |
| `just test` | Run tests against Python 3.13. |
| `just test 3.8` | Run tests against a specific Python version. |
| `just lint` | Check formatting and run Ruff. |
| `just fmt` | Format files and apply Ruff fixes. |
| `just build` | Build the wheel and source distribution in `dist/`. |
| `just smoke` | Run `posit --help` from the latest built wheel. |
| `just install` | Install the latest built wheel as a non-editable uv tool. |
| `just uninstall` | Remove the uv-managed `posit-cli` tool. |
| `just clean` | Remove build, test, and lint artifacts. |

`just smoke` expects a wheel to exist in `dist/`, so run `just build` first unless another command has already built one.

## Dependency Changes

Runtime dependencies and optional test/lint dependencies are declared in `pyproject.toml`. When changing them:

1. Update `pyproject.toml`.
2. Run `uv lock` to update `uv.lock`.
3. Run `just deps` to sync the local environment.
4. Include both `pyproject.toml` and `uv.lock` in the change.

CI checks that the lockfile is current with `uv lock --locked`.

## Before Opening A Pull Request

Run the checks relevant to your change. The normal local validation sequence is:

```console
just deps
just lint
just test
just build
just smoke
```

CI also runs the test suite against Python 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, and 3.14. Add or update tests when changing behavior, and update user-facing documentation in `README.md` when the CLI changes.

Keep commits focused and use Conventional Commit messages, such as `fix: handle expired Connect tokens` or `docs: clarify local setup`.

## Releases

Release preparation and publishing are documented in [RELEASE.md](RELEASE.md). In particular, do not add a hard-coded version to `pyproject.toml`; release versions come from Git tags through `hatch-vcs`.
