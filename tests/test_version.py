"""Tests for Connect server version output and connection selection."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner
from rsconnect.api import RSConnectClient, RSConnectException, RSConnectServer

from posit_cli.__main__ import cli


@pytest.mark.parametrize(
    "settings, output", [({"version": "2026.10.0"}, "2026.10.0\n"), ({}, "\n")]
)
def test_server_version(settings, output, monkeypatch):
    monkeypatch.delenv("CONNECT_SERVER_VERSION", raising=False)
    client = RSConnectClient(RSConnectServer("https://connect.example.com", api_key="key"))
    with patch("posit_cli.connect.version.RSConnectExecutor") as executor:
        with patch.object(client, "get", return_value=settings) as get:
            executor.return_value.client = client
            result = CliRunner().invoke(cli, ["connect", "version"])
    assert result.exit_code == 0, result.output
    assert result.output == output
    get.assert_called_once_with("server_settings")
    executor.assert_called_once_with(
        ctx=None, name=None, url=None, api_key=None, insecure=False, cacert=None
    )


def test_server_version_override(monkeypatch):
    monkeypatch.setenv("CONNECT_SERVER_VERSION", "2026.09.0")
    client = RSConnectClient(RSConnectServer("https://connect.example.com", api_key="key"))
    with patch("posit_cli.connect.version.RSConnectExecutor") as executor:
        with patch.object(client, "get") as get:
            executor.return_value.client = client
            result = CliRunner().invoke(cli, ["connect", "version"])
    assert result.exit_code == 0, result.output
    assert result.output == "2026.09.0\n"
    get.assert_not_called()


@pytest.mark.parametrize("use_env", [False, True])
def test_connection_options(tmp_path, use_env):
    cacert = tmp_path / "ca.pem"
    cacert.write_text("certificate")
    args = ["connect", "version", "--name", "production"]
    env = {}
    if use_env:
        env = {
            "CONNECT_SERVER": "https://connect.example.com",
            "CONNECT_API_KEY": "key",
            "CONNECT_INSECURE": "true",
            "CONNECT_CA_CERTIFICATE": str(cacert),
        }
    else:
        args += [
            "-s",
            "https://connect.example.com",
            "-k",
            "key",
            "--no-tls-verify",
            "-c",
            str(cacert),
        ]
    with patch("posit_cli.connect.version.RSConnectExecutor") as executor:
        executor.return_value.client.server_version.return_value = "2026.10.0"
        result = CliRunner().invoke(cli, args, env=env)
    assert result.exit_code == 0, result.output
    executor.assert_called_once_with(
        ctx=None,
        name="production",
        url="https://connect.example.com",
        api_key="key",
        insecure=True,
        cacert=str(cacert),
    )


@pytest.mark.parametrize("stage", ["selection", "request"])
def test_errors(stage):
    with patch("posit_cli.connect.version.RSConnectExecutor") as executor:
        error = RSConnectException("unable to retrieve server version")
        if stage == "selection":
            executor.side_effect = error
        else:
            executor.return_value.client.server_version.side_effect = error
        result = CliRunner().invoke(cli, ["connect", "version"])
    assert result.exit_code == 1
    assert result.output == "Error: unable to retrieve server version\n"
    assert isinstance(result.exception, SystemExit)


def test_help():
    result = CliRunner().invoke(cli, ["connect", "version", "-h"])
    assert result.exit_code == 0
    assert "Connect server version" in result.output
    assert "--server" in result.output
