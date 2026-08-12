"""Tests for the Publisher-backed init and publish commands."""

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from rsconnect.exception import RSConnectException

from posit_cli.__main__ import cli


init_mod = importlib.import_module("posit_cli.connect.init")
publish_mod = importlib.import_module("posit_cli.connect.publish")


@pytest.fixture
def runner():
    return CliRunner()


def test_init_without_flags_requires_tty(runner):
    with patch.object(init_mod, "_is_interactive", return_value=False):
        with patch.object(init_mod.questionary, "select") as select:
            result = runner.invoke(cli, ["connect", "init"])

    assert result.exit_code == 2
    assert "Interactive input is unavailable" in result.output
    assert not select.called


def test_init_explicit_flags_build_request(runner):
    initialized = SimpleNamespace(
        config_name="sales", config_path="/project/.posit/publish/sales.toml"
    )
    with patch.object(init_mod, "initialize_project", return_value=initialized) as initialize:
        result = runner.invoke(
            cli,
            [
                "connect",
                "init",
                "--type",
                "python-fastapi",
                "--entrypoint",
                "app.py:app",
                "--title",
                "Sales API",
                "--config",
                "sales",
                "--package-file",
                "pyproject.toml",
                "--package-manager",
                "uv",
                "--file",
                "app.py",
                "--file",
                "src/**",
            ],
        )

    assert result.exit_code == 0, result.output
    request = initialize.call_args.args[0]
    assert request.content_type == "python-fastapi"
    assert request.entrypoint == "app.py:app"
    assert request.title == "Sales API"
    assert request.config_name == "sales"
    assert request.python == {
        "package_file": "pyproject.toml",
        "package_manager": "uv",
    }
    assert request.files == ("app.py", "src/**")
    assert "Initialized sales" in result.output


def test_init_writes_publisher_config(runner):
    from rsconnect.publisher import config

    with runner.isolated_filesystem():
        Path("app.py").write_text("app = object()\n", encoding="utf-8")
        Path("pyproject.toml").write_text("[project]\nname = 'sales'\n", encoding="utf-8")
        result = runner.invoke(
            cli,
            [
                "connect",
                "init",
                "--type",
                "python-fastapi",
                "--entrypoint",
                "app.py:app",
                "--title",
                "Sales API",
                "--config",
                "sales",
                "--package-file",
                "pyproject.toml",
                "--package-manager",
                "uv",
            ],
        )

        config_path = Path(".posit/publish/sales.toml")
        assert result.exit_code == 0, result.output
        assert config_path.is_file()
        initialized = config.read_config(str(config_path))
        assert initialized.type == "python-fastapi"
        assert initialized.entrypoint == "app.py:app"
        assert initialized.title == "Sales API"
        assert initialized.python == {
            "package_file": "pyproject.toml",
            "package_manager": "uv",
        }


def test_init_explicit_mode_requires_type_and_entrypoint(runner):
    result = runner.invoke(cli, ["connect", "init", "--title", "Incomplete"])

    assert result.exit_code == 2
    assert "--type and --entrypoint are required" in result.output


def test_init_quarto_requires_version(runner):
    result = runner.invoke(
        cli,
        [
            "connect",
            "init",
            "--type",
            "quarto-static",
            "--entrypoint",
            "report.qmd",
        ],
    )

    assert result.exit_code == 2
    assert "--quarto-version is required" in result.output


def test_interactive_init_collects_python_answers(runner):
    initialized = SimpleNamespace(
        config_name="sales", config_path="/project/.posit/publish/sales.toml"
    )
    with patch.object(init_mod, "_is_interactive", return_value=True):
        with patch.object(
            init_mod,
            "_ask",
            side_effect=[
                "python-fastapi",
                "app.py",
                "Sales API",
                "requirements.txt",
                "uv",
                True,
            ],
        ):
            with patch.object(
                init_mod, "initialize_project", return_value=initialized
            ) as initialize:
                result = runner.invoke(cli, ["connect", "init"])

    assert result.exit_code == 0, result.output
    request = initialize.call_args.args[0]
    assert request.content_type == "python-fastapi"
    assert request.entrypoint == "app.py"
    assert request.title == "Sales API"
    assert request.python == {
        "package_file": "requirements.txt",
        "package_manager": "uv",
    }
    assert request.files == ("*",)
    assert "Connect" in result.output
    assert "  / /\\" in result.output
    assert " | |  | Connect" in result.output
    assert "  \\ \\/" in result.output
    assert "Configure a project for Posit Connect" in result.output
    assert "[OK] Publisher project initialized" in result.output
    assert "posit connect publish . --server <connect-url>" in result.output


def test_interactive_init_detects_entrypoints_and_defaults(runner):
    with runner.isolated_filesystem():
        Path("worker.py").write_text("", encoding="utf-8")
        Path("main.py").write_text("", encoding="utf-8")
        Path("app.py").write_text("", encoding="utf-8")
        Path("notes.txt").write_text("", encoding="utf-8")

        choices, default = init_mod._entrypoint_choices(".", "python-fastapi")
        package_choices, package_default = init_mod._package_file_choices()

    assert [choice.value for choice in choices] == [
        "app.py",
        "main.py",
        "worker.py",
        init_mod._OTHER_ENTRYPOINT,
    ]
    assert default == "app.py"
    assert [choice.value for choice in package_choices] == [
        "requirements.txt",
        "pyproject.toml",
        init_mod._OTHER_PACKAGE_FILE,
    ]
    assert package_default == "requirements.txt"
    assert init_mod._PYTHON_PACKAGE_MANAGERS[0] == "uv"


def test_interactive_init_detects_content_specific_entrypoints(runner):
    with runner.isolated_filesystem():
        Path("app.py").write_text("", encoding="utf-8")
        Path("report.ipynb").write_text("{}", encoding="utf-8")
        Path("index.html").write_text("", encoding="utf-8")

        notebook_choices, notebook_default = init_mod._entrypoint_choices(".", "jupyter-notebook")
        html_choices, html_default = init_mod._entrypoint_choices(".", "html")

    assert [choice.value for choice in notebook_choices[:-1]] == ["report.ipynb"]
    assert notebook_default == "report.ipynb"
    assert [choice.value for choice in html_choices[:-1]] == ["index.html"]
    assert html_default == "index.html"


def test_interactive_init_accepts_custom_entrypoint_and_package_file():
    with patch.object(
        init_mod,
        "_ask",
        side_effect=[
            "python-fastapi",
            init_mod._OTHER_ENTRYPOINT,
            "src/api.py:create_app",
            "Custom API",
            init_mod._OTHER_PACKAGE_FILE,
            "requirements/connect.txt",
            "uv",
            True,
        ],
    ):
        answers = init_mod.collect_init_answers(".")

    assert answers["entrypoint"] == "src/api.py:create_app"
    assert answers["python"] == {
        "package_file": "requirements/connect.txt",
        "package_manager": "uv",
    }


def test_interactive_quarto_asks_mode_and_version(runner):
    initialized = SimpleNamespace(
        config_name="report", config_path="/project/.posit/publish/report.toml"
    )
    with patch.object(init_mod, "_is_interactive", return_value=True):
        with patch.object(
            init_mod,
            "_ask",
            side_effect=[
                "quarto-static",
                "shiny",
                "report.qmd",
                "Report",
                "1.6.0",
                True,
            ],
        ):
            with patch.object(
                init_mod, "initialize_project", return_value=initialized
            ) as initialize:
                result = runner.invoke(cli, ["connect", "init"])

    assert result.exit_code == 0, result.output
    request = initialize.call_args.args[0]
    assert request.content_type == "quarto-shiny"
    assert request.quarto == {"version": "1.6.0"}


def test_interactive_init_aborts_cleanly(runner):
    prompt = MagicMock()
    prompt.unsafe_ask.side_effect = KeyboardInterrupt
    with patch.object(init_mod, "_is_interactive", return_value=True):
        with patch.object(init_mod.questionary, "select", return_value=prompt):
            result = runner.invoke(cli, ["connect", "init"])

    assert result.exit_code == 1
    assert "Aborted!" in result.output


def test_init_wraps_rsconnect_errors(runner):
    with patch.object(
        init_mod,
        "initialize_project",
        side_effect=RSConnectException("configuration already exists"),
    ):
        result = runner.invoke(
            cli,
            [
                "connect",
                "init",
                "--type",
                "html",
                "--entrypoint",
                "index.html",
            ],
        )

    assert result.exit_code == 1
    assert "configuration already exists" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_publish_maps_all_request_fields(runner):
    published = SimpleNamespace(content_url="https://connect.example/content/abc/")
    with patch.object(publish_mod, "publish_project", return_value=published) as publish:
        result = runner.invoke(
            cli,
            [
                "connect",
                "publish",
                ".",
                "--config",
                "sales-api",
                "--deployment",
                "production",
                "--server",
                "https://connect.example",
                "--api-key",
                "secret",
                "--snowflake-connection-name",
                "snowflake-prod",
                "--no-tls-verify",
                "--content-id",
                "guid-1",
                "--draft",
                "--no-verify",
                "--exclude-renv",
                "--metadata",
                "git_commit=abc",
                "--no-metadata",
            ],
        )

    assert result.exit_code == 0, result.output
    request = publish.call_args.args[0]
    assert request.config_name == "sales-api"
    assert request.deployment_name == "production"
    assert request.server == "https://connect.example"
    assert request.api_key == "secret"
    assert request.snowflake_connection_name == "snowflake-prod"
    assert request.insecure is True
    assert request.content_id == "guid-1"
    assert request.draft is True
    assert request.verify is False
    assert request.exclude_renv is True
    assert request.metadata == ("git_commit=abc",)
    assert request.no_metadata is True
    assert request.ctx is not None
    assert result.output.strip() == published.content_url


def test_publish_server_name_alias(runner):
    published = SimpleNamespace(content_url="https://connect.example/content/abc/")
    with patch.object(publish_mod, "publish_project", return_value=published) as publish:
        result = runner.invoke(cli, ["connect", "publish", "--name", "production"])

    assert result.exit_code == 0, result.output
    assert publish.call_args.args[0].server_name == "production"


def test_publish_wraps_rsconnect_errors(runner):
    with patch.object(
        publish_mod,
        "publish_project",
        side_effect=RSConnectException("specify server for the first publish"),
    ):
        result = runner.invoke(cli, ["connect", "publish"])

    assert result.exit_code == 1
    assert "specify server for the first publish" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
