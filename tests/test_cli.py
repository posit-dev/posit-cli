"""Smoke tests for the command tree and a guard on rsconnect's surface."""

import pytest
from click.testing import CliRunner

from posit_cli.__main__ import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_top_level_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "connect" in result.output


def test_connect_mounts_api_command(runner):
    result = runner.invoke(cli, ["connect", "--help"])
    assert result.exit_code == 0
    assert "api" in result.output
    assert "run" in result.output


# rsconnect commands we expect to re-expose under `posit connect`.
EXPECTED_RSCONNECT_COMMANDS = [
    "add",
    "deploy",
    "list",
    "details",
    "remove",
    "bootstrap",
    "login",
    "logout",
]


@pytest.mark.parametrize("name", EXPECTED_RSCONNECT_COMMANDS)
def test_rsconnect_command_present(runner, name):
    """Guard: fail loudly if an upstream rsconnect command is renamed/dropped."""
    from posit_cli.connect import connect

    assert name in connect.commands


def test_deploy_passthrough(runner):
    result = runner.invoke(cli, ["connect", "deploy", "--help"])
    assert result.exit_code == 0
    # a representative rsconnect deploy target
    assert "streamlit" in result.output
