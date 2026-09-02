# posit-cli task runner. Run `just --list` to see recipes.

# Sync project and development dependencies into the project environment
deps:
    uv sync --all-extras

# Run the test suite against a single Python version (default 3.13)
test py="3.13":
    uv run --python {{py}} --extra test pytest tests

# Run tests that publish to a live Connect instance.
integration:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ ! -f .connect-license.lic ]]; then
        echo "Missing .connect-license.lic; see AGENTS.md." >&2
        exit 1
    fi
    uvx --from git+https://github.com/posit-dev/with-connect.git \
        with-connect --license .connect-license.lic -- \
        uv run --extra test pytest -m integration -vv tests/integration

# Check formatting and lint
lint:
    uv run --extra lint ruff format --check
    uv run --extra lint ruff check

# Auto-format and apply lint fixes
fmt:
    uv run --extra lint ruff format
    uv run --extra lint ruff check --fix

# Build wheel + sdist
build:
    uv build

# Smoke-test the most recently built wheel (no project install)
smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    WHL=$(ls -t dist/*.whl | head -1)
    uv run --no-project --with "$WHL" posit --help

# Install the most recently built wheel as a standalone uv tool
install: build
    uv tool install --force "$(ls -t dist/*.whl | head -1)"

# Install the project as an editable standalone uv tool
dev:
    uv tool install --editable --force .

# Remove the installed standalone uv tool
uninstall:
    uv tool uninstall posit-cli

# Print the version that a build gets from the current git state
version:
    @uvx hatch version

# Remove build/test artifacts
clean:
    rm -rf .coverage .pytest_cache .ruff_cache build dist *.egg-info
