"""Tests for the Publisher-backed publish workflow."""

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


def test_publish_init_without_flags_requires_tty(runner):
    with patch.object(init_mod, "_is_interactive", return_value=False):
        with patch.object(init_mod.questionary, "select") as select:
            result = runner.invoke(cli, ["connect", "publish", "--init"])

    assert result.exit_code == 2
    assert "Interactive input is unavailable" in result.output
    assert not select.called


def test_publish_init_explicit_flags_build_request(runner):
    initialized = SimpleNamespace(
        config_name="sales", config_path="/project/.posit/publish/sales.toml"
    )
    with patch.object(init_mod, "initialize_project", return_value=initialized) as initialize:
        result = runner.invoke(
            cli,
            [
                "connect",
                "publish",
                "--init",
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
    assert request.files == ("app.py", "src/**", "/pyproject.toml")
    assert "Configured sales" in result.output


def test_publish_init_writes_publisher_config(runner):
    from rsconnect.publisher import config

    with runner.isolated_filesystem():
        Path("app.py").write_text("app = object()\n", encoding="utf-8")
        Path("pyproject.toml").write_text("[project]\nname = 'sales'\n", encoding="utf-8")
        result = runner.invoke(
            cli,
            [
                "connect",
                "publish",
                "--init",
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
        assert "*" in initialized.files
        assert "/app.py" in initialized.files
        assert "/pyproject.toml" in initialized.files


def test_publish_init_explicit_mode_requires_type_and_entrypoint(runner):
    result = runner.invoke(cli, ["connect", "publish", "--init", "--title", "Incomplete"])

    assert result.exit_code == 2
    assert "--type and --entrypoint are required" in result.output


def test_publish_init_quarto_requires_version(runner):
    result = runner.invoke(
        cli,
        [
            "connect",
            "publish",
            "--init",
            "--type",
            "quarto-static",
            "--entrypoint",
            "report.qmd",
        ],
    )

    assert result.exit_code == 2
    assert "--quarto-version is required" in result.output


def test_interactive_publish_init_collects_python_answers(runner):
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
                init_mod._INCLUDE_ALL_FILES,
            ],
        ):
            with patch.object(
                init_mod, "initialize_project", return_value=initialized
            ) as initialize:
                result = runner.invoke(cli, ["connect", "publish", "--init"])

    assert result.exit_code == 0, result.output
    request = initialize.call_args.args[0]
    assert request.content_type == "python-fastapi"
    assert request.entrypoint == "app.py"
    assert request.title == "Sales API"
    assert request.python == {
        "package_file": "requirements.txt",
        "package_manager": "uv",
    }
    assert request.files == ("*", "/app.py", "/requirements.txt")
    assert "Connect" in result.output
    assert "  / /\\" in result.output
    assert " | |  | Posit Connect" in result.output
    assert "  \\ \\/" in result.output
    assert "Configure a project for Posit Connect" in result.output
    assert "[OK] Project configured for publishing" in result.output
    assert "posit connect publish . --server <connect-url>" in result.output


def test_interactive_publish_init_detects_entrypoints_and_defaults(runner):
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
        init_mod._OTHER_ENTRYPOINT,
    ]
    assert default == "app.py"
    assert [choice.value for choice in package_choices] == [
        "requirements.txt",
        "pyproject.toml",
        init_mod._OTHER_PACKAGE_FILE,
    ]
    assert package_default == "requirements.txt"
    assert publish_mod._PYTHON_PACKAGE_MANAGERS[0] == "uv"


def test_interactive_publish_init_detects_content_specific_entrypoints(runner):
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


def test_manual_file_choices_precheck_entrypoint_and_dependencies(runner):
    with runner.isolated_filesystem():
        Path("src").mkdir()
        Path("src/api.py").write_text("", encoding="utf-8")
        Path("app.py").write_text("", encoding="utf-8")
        Path("requirements.txt").write_text("", encoding="utf-8")
        Path("README.md").write_text("", encoding="utf-8")

        choices = init_mod._top_level_file_choices(
            ".",
            "app.py",
            "requirements.txt",
        )

    assert [choice.value for choice in choices] == [
        "/src/",
        "/app.py",
        "/README.md",
        "/requirements.txt",
    ]
    assert {choice.value: choice.checked for choice in choices} == {
        "/src/": False,
        "/app.py": True,
        "/README.md": False,
        "/requirements.txt": True,
    }


def test_required_files_are_added_after_manual_selection():
    files = init_mod._include_required_files(
        ".",
        "src/api.py:create_app",
        "requirements/connect.txt",
        ("/README.md",),
    )

    assert files == (
        "/README.md",
        "/src/api.py",
        "/requirements/connect.txt",
    )


def test_interactive_publish_init_accepts_custom_entrypoint_and_package_file():
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
            init_mod._SELECT_FILES_MANUALLY,
            ["/src/", "/requirements/"],
        ],
    ):
        answers = init_mod.collect_init_answers(".")

    assert answers["entrypoint"] == "src/api.py:create_app"
    assert answers["python"] == {
        "package_file": "requirements/connect.txt",
        "package_manager": "uv",
    }
    assert answers["files"] == ("/src/", "/requirements/")


def test_interactive_publish_init_quarto_asks_mode_and_version(runner):
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
                init_mod._INCLUDE_ALL_FILES,
            ],
        ):
            with patch.object(
                init_mod, "initialize_project", return_value=initialized
            ) as initialize:
                result = runner.invoke(cli, ["connect", "publish", "--init"])

    assert result.exit_code == 0, result.output
    request = initialize.call_args.args[0]
    assert request.content_type == "quarto-shiny"
    assert request.quarto == {"version": "1.6.0"}
    assert request.files == ("*", "/report.qmd")


def test_interactive_publish_init_aborts_cleanly(runner):
    prompt = MagicMock()
    prompt.unsafe_ask.side_effect = KeyboardInterrupt
    with patch.object(init_mod, "_is_interactive", return_value=True):
        with patch.object(init_mod.questionary, "select", return_value=prompt):
            result = runner.invoke(cli, ["connect", "publish", "--init"])

    assert result.exit_code == 1
    assert "Aborted!" in result.output


def test_publish_init_wraps_rsconnect_errors(runner):
    with patch.object(
        init_mod,
        "initialize_project",
        side_effect=RSConnectException("configuration already exists"),
    ):
        result = runner.invoke(
            cli,
            [
                "connect",
                "publish",
                "--init",
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
    with patch.object(publish_mod, "discover_configs", return_value=["config.toml"]):
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
    with patch.object(publish_mod, "discover_configs", return_value=["config.toml"]):
        with patch.object(publish_mod, "publish_project", return_value=published) as publish:
            result = runner.invoke(cli, ["connect", "publish", "--name", "production"])

    assert result.exit_code == 0, result.output
    assert publish.call_args.args[0].server_name == "production"


def test_publish_wraps_rsconnect_errors(runner):
    with patch.object(publish_mod, "discover_configs", return_value=["config.toml"]):
        with patch.object(
            publish_mod,
            "publish_project",
            side_effect=RSConnectException("specify server for the first publish"),
        ):
            result = runner.invoke(cli, ["connect", "publish"])

    assert result.exit_code == 1
    assert "specify server for the first publish" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_publish_auto_initializes_fresh_interactive_project(runner):
    initialized = SimpleNamespace(
        config_name="sales", config_path="/project/.posit/publish/sales.toml"
    )
    published = SimpleNamespace(content_url="https://connect.example/content/abc/")
    with patch.object(publish_mod, "discover_configs", return_value=[]):
        with patch.object(init_mod, "_is_interactive", return_value=True):
            with patch.object(
                init_mod, "initialize_publish_project", return_value=initialized
            ) as initialize:
                with patch.object(
                    publish_mod, "publish_project", return_value=published
                ) as publish:
                    result = runner.invoke(cli, ["connect", "publish"])

    assert result.exit_code == 0, result.output
    assert initialize.call_args.kwargs["show_success"] is False
    assert publish.call_args.args[0].config_name == "sales"
    assert result.output.strip() == published.content_url


def test_publish_fresh_noninteractive_project_explains_init(runner):
    with patch.object(publish_mod, "discover_configs", return_value=[]):
        with patch.object(init_mod, "_is_interactive", return_value=False):
            result = runner.invoke(cli, ["connect", "publish"])

    assert result.exit_code == 2
    assert "No Publisher configuration found" in result.output
    assert "posit connect publish --init" in result.output


def test_publish_setup_options_require_init(runner):
    result = runner.invoke(
        cli,
        ["connect", "publish", "--type", "python-fastapi", "--entrypoint", "app.py"],
    )

    assert result.exit_code == 2
    assert "Project setup options require --init" in result.output
