# posit-cli task runner. Run `just --list` to see recipes.

# Run the test suite against a single Python version (default 3.13)
test py="3.13":
    uv run --python {{py}} --extra test pytest tests

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
    WHL=$(ls dist/*.whl | head -1)
    uv run --no-project --with "$WHL" posit --help

# Install the most recently built wheel into the active environment
install: build
    uv pip install dist/*.whl

# Print the current version
version:
    @uv version --short

# Remove build/test artifacts
clean:
    rm -rf .coverage .pytest_cache .ruff_cache build dist *.egg-info
