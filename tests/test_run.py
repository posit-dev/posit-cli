"""Unit tests for the legacy-API `posit connect run` command."""

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from posit_cli.__main__ import cli
from posit_cli.connect.run import (
    _RunDependencies,
    _RunRequest,
    _build_bundle,
    _build_r_bundle,
    _client_connection,
    _execute_run,
    _rpy2_wrapper_source,
    _wrapper_source,
)
from rsconnect.http_support import HTTPServer
from rsconnect.models import AppModes


@pytest.fixture
def runner():
    return CliRunner()


def _app_response(body: bytes, status: int = 200):
    return SimpleNamespace(response_body=body, status=status, exception=None)


def _mock_executor():
    executor = MagicMock()
    client = executor.client
    client.content_create.return_value = {
        "guid": "content-123",
        "content_url": "https://connect.example.com/content/content-123/",
    }
    client.upload_bundle.return_value = {"id": "bundle-123"}
    client.content_deploy.return_value = {"task_id": "task-123"}
    client.wait_for_task.return_value = ([], {"code": 0})
    client.delete.return_value = None
    executor.client = client
    return executor


def test_run_creates_deploys_invokes_and_deletes_temporary_content(runner, tmp_path):
    script = tmp_path / "hello.py"
    script.write_text("print('hello from Connect')\n", encoding="utf-8")
    executor = _mock_executor()
    response = _app_response(b"hello from Connect\n")

    with patch("posit_cli.connect.run.RSConnectExecutor", return_value=executor), patch(
        "posit_cli.connect.run._build_bundle", return_value=io.BytesIO(b"bundle")
    ) as build_bundle, patch(
        "posit_cli.connect.run._content_response", return_value=response
    ) as content_response:
        result = runner.invoke(cli, ["connect", "run", str(script), "--", "one", "--two"])

    assert result.exit_code == 0, result.output
    assert result.output == "hello from Connect\n"
    build_bundle.assert_called_once_with(script, ("one", "--two"), None)
    content_response.assert_called_once_with(
        executor.client, "https://connect.example.com/content/content-123/"
    )
    executor.client.content_create.assert_called_once()
    executor.client.upload_bundle.assert_called_once()
    executor.client.content_deploy.assert_called_once_with("content-123", bundle_id="bundle-123")
    executor.client.wait_for_task.assert_called_once_with(
        "task-123",
        log_callback=None,
        raise_on_error=False,
    )
    executor.client.delete.assert_called_once_with("v1/content/content-123", decode_response=False)
    executor.setup_client.assert_not_called()


class _TrackingClient(HTTPServer):
    def __init__(self, events):
        super().__init__("http://127.0.0.1")
        self.events = events

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, *args):
        self.events.append("exit")

    def content_create(self, name):
        self.events.append("create")
        return {"guid": "content-123", "content_url": "https://connect.example.com/content-123"}

    def upload_bundle(self, content_guid, bundle):
        self.events.append("upload")
        return {"id": "bundle-123"}

    def content_deploy(self, content_guid, *, bundle_id):
        self.events.append("deploy")
        return {"task_id": "task-123"}

    def wait_for_task(self, task_id, *, log_callback, raise_on_error):
        self.events.append("wait")
        return ([], {"code": 0})


def test_run_reuses_client_connection_through_cleanup(tmp_path):
    script = tmp_path / "hello.py"
    script.write_text("print('hello')\n", encoding="utf-8")
    events = []
    client = _TrackingClient(events)
    executor = SimpleNamespace(client=client)
    response = _app_response(b"hello\n")

    def build_bundle(path, program_args, runtime):
        events.append("build")
        return io.BytesIO(b"bundle")

    def invoke_content(content_client, content_url):
        events.append("invoke")
        return response

    def delete_content(content_client, content_guid):
        events.append("delete")

    dependencies = _RunDependencies(
        executor_factory=lambda **kwargs: executor,
        bundle_builder=build_bundle,
        content_invoker=invoke_content,
        content_deleter=delete_content,
    )
    request = _RunRequest(
        path=script,
        program_args=(),
        runtime=None,
        job_name=None,
        detach=False,
        server_name=None,
        server=None,
        api_key=None,
        insecure=False,
        cacert=None,
    )

    _execute_run(request, dependencies)

    assert events == [
        "enter",
        "create",
        "build",
        "upload",
        "deploy",
        "wait",
        "invoke",
        "delete",
        "exit",
    ]


def test_client_connection_leaves_alternate_clients_untouched():
    client = object()

    with _client_connection(client) as connected:
        assert connected is client


def test_run_accepts_directory(runner, tmp_path):
    project = tmp_path / "hello-world"
    project.mkdir()
    (project / "app.py").write_text("print('hello from Connect')\n", encoding="utf-8")
    executor = _mock_executor()

    with patch("posit_cli.connect.run.RSConnectExecutor", return_value=executor), patch(
        "posit_cli.connect.run._build_bundle", return_value=io.BytesIO(b"bundle")
    ) as build_bundle, patch(
        "posit_cli.connect.run._content_response",
        return_value=_app_response(b"hello from Connect\n"),
    ):
        result = runner.invoke(cli, ["connect", "run", str(project), "--", "one"])

    assert result.exit_code == 0, result.output
    assert result.output == "hello from Connect\n"
    build_bundle.assert_called_once_with(project, ("one",), None)


def test_run_detach_prints_content_url_and_keeps_content(runner, tmp_path):
    script = tmp_path / "hello.py"
    script.write_text("print('hello')\n", encoding="utf-8")
    executor = _mock_executor()

    with patch("posit_cli.connect.run.RSConnectExecutor", return_value=executor), patch(
        "posit_cli.connect.run._build_bundle", return_value=io.BytesIO(b"bundle")
    ), patch("posit_cli.connect.run._content_response") as content_response:
        result = runner.invoke(cli, ["connect", "run", str(script), "--detach"])

    assert result.exit_code == 0, result.output
    assert result.output == "https://connect.example.com/content/content-123/\n"
    content_response.assert_not_called()


def test_run_returns_nonzero_for_content_failure_and_still_deletes(runner, tmp_path):
    script = tmp_path / "hello.py"
    script.write_text("raise SystemExit(3)\n", encoding="utf-8")
    executor = _mock_executor()

    with patch("posit_cli.connect.run.RSConnectExecutor", return_value=executor), patch(
        "posit_cli.connect.run._build_bundle", return_value=io.BytesIO(b"bundle")
    ), patch(
        "posit_cli.connect.run._content_response",
        return_value=_app_response(b"failed\n", status=500),
    ):
        result = runner.invoke(cli, ["connect", "run", str(script)])

    assert result.exit_code == 1
    assert result.output == "failed\n"


def test_run_accepts_r_scripts(runner, tmp_path):
    script = tmp_path / "hello.R"
    script.write_text('cat("hello from R\\n")\n', encoding="utf-8")
    executor = _mock_executor()

    with patch("posit_cli.connect.run.RSConnectExecutor", return_value=executor), patch(
        "posit_cli.connect.run._build_bundle", return_value=io.BytesIO(b"bundle")
    ) as build_bundle, patch(
        "posit_cli.connect.run._content_response", return_value=_app_response(b"hello from R\n")
    ):
        result = runner.invoke(cli, ["connect", "run", str(script)])

    assert result.exit_code == 0, result.output
    assert result.output == "hello from R\n"
    build_bundle.assert_called_once_with(script, (), None)


def test_run_rejects_unsupported_files(runner, tmp_path):
    program = tmp_path / "hello.txt"
    program.write_text("hello\n", encoding="utf-8")

    result = runner.invoke(cli, ["connect", "run", str(program)])

    assert result.exit_code != 0
    assert "PATH must be a Python or R file ending in .py or .R" in result.output


def test_run_rejects_directory_without_entrypoint(runner, tmp_path):
    project = tmp_path / "hello-world"
    project.mkdir()
    (project / "README.md").write_text("hello\n", encoding="utf-8")

    result = runner.invoke(cli, ["connect", "run", str(project)])

    assert result.exit_code != 0
    assert "PATH directory must contain a runnable Python or R source file" in result.output


def test_run_rejects_directory_with_ambiguous_entrypoints(runner, tmp_path):
    project = tmp_path / "hello-world"
    project.mkdir()
    (project / "first.py").write_text("print('first')\n", encoding="utf-8")
    (project / "second.py").write_text("print('second')\n", encoding="utf-8")

    result = runner.invoke(cli, ["connect", "run", str(project)])

    assert result.exit_code != 0
    assert "PATH directory must contain one runnable source file" in result.output


def test_wrapper_uses_json_encoded_program_arguments():
    source = _wrapper_source(("Ada Lovelace", 'quote "this"'))

    assert 'PROGRAM_ARGS = ["Ada Lovelace", "quote \\"this\\""]' in source
    assert "from flask" not in source
    assert "def app(_environ, start_response):" in source
    assert "subprocess.run(" in source


def test_build_bundle_preserves_directory_files_and_uses_app_entrypoint(tmp_path):
    project = tmp_path / "hello-world"
    project.mkdir()
    (project / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (project / "data.txt").write_text("fixture\n", encoding="utf-8")
    (project / "lib").mkdir()
    (project / "lib" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    observed = {}

    def fake_make_api_bundle(directory, entrypoint, app_mode, environment, extra_files, excludes):
        root = Path(directory)
        observed["files"] = sorted(
            path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
        )
        observed["wrapper"] = (root / "runner.py").read_text(encoding="utf-8")
        observed["requirements"] = (root / "requirements.txt").read_text(encoding="utf-8")
        observed["entrypoint"] = entrypoint
        observed["app_mode"] = app_mode
        observed["environment"] = environment
        observed["extra_files"] = extra_files
        observed["excludes"] = excludes
        return io.BytesIO(b"bundle")

    with patch(
        "posit_cli.connect.run.Environment.create_python_environment",
        return_value="environment",
    ), patch("posit_cli.connect.run.make_api_bundle", side_effect=fake_make_api_bundle):
        bundle = _build_bundle(project, ("arg",), "python3.12")

    assert bundle.read() == b"bundle"
    assert observed["files"] == [
        "app.py",
        "data.txt",
        "lib/helper.py",
        "pyproject.toml",
        "requirements.txt",
        "runner.py",
    ]
    assert 'PROGRAM = "app.py"' in observed["wrapper"]
    assert 'PROGRAM_ARGS = ["arg"]' in observed["wrapper"]
    assert observed["entrypoint"] == "runner:app"
    assert observed["app_mode"] is AppModes.PYTHON_API
    assert observed["environment"] == "environment"
    assert observed["extra_files"] == []
    assert observed["excludes"] == []


def test_build_r_bundle_accepts_directory(tmp_path):
    project = tmp_path / "hello-world"
    project.mkdir()
    (project / "app.R").write_text('cat("hello\\n")\n', encoding="utf-8")
    observed = {}

    def fake_make_api_bundle(
        directory,
        entrypoint,
        app_mode,
        environment,
        extra_files,
        excludes,
        r_environment,
    ):
        root = Path(directory)
        observed["files"] = sorted(
            path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
        )
        observed["wrapper"] = (root / "runner.py").read_text(encoding="utf-8")
        observed["requirements"] = (root / "requirements.txt").read_text(encoding="utf-8")
        observed["entrypoint"] = entrypoint
        observed["app_mode"] = app_mode
        observed["environment"] = environment
        observed["extra_files"] = extra_files
        observed["excludes"] = excludes
        observed["r_environment"] = r_environment
        return io.BytesIO(b"bundle")

    with patch(
        "posit_cli.connect.run.Environment.create_python_environment",
        return_value="environment",
    ), patch("posit_cli.connect.run.make_api_bundle", side_effect=fake_make_api_bundle):
        bundle = _build_bundle(project, (), "r4.5")

    assert bundle.read() == b"bundle"
    assert observed["files"] == [
        "app.R",
        "pyproject.toml",
        "requirements.txt",
        "runner.py",
    ]
    assert 'PROGRAM = "app.R"' in observed["wrapper"]
    assert observed["requirements"] == "rpy2\n"
    assert observed["entrypoint"] == "runner:app"
    assert observed["app_mode"] is AppModes.PYTHON_API
    assert observed["environment"] == "environment"
    assert observed["extra_files"] == []
    assert observed["excludes"] == []
    assert observed["r_environment"].r_version == "4.5"


def test_r_wrapper_uses_rpy2_and_encoded_program_arguments():
    source = _rpy2_wrapper_source(("Ada Lovelace", 'quote "this"'))

    assert 'PROGRAM_ARGS = ["Ada Lovelace", "quote \\"this\\""]' in source
    assert "import rpy2.robjects as robjects" in source
    assert "sys.source(basename(path), envir = execution_env)" in source
    assert "commandArgs" in source
    assert "logging.disable(logging.CRITICAL)" in source
    assert "logging.disable(previous_logging_disable)" in source
    assert "plumber" not in source


def test_build_bundle_uses_standard_python_api_manifest(tmp_path):
    script = tmp_path / "hello.py"
    script.write_text("print('hello')\n", encoding="utf-8")
    observed = {}

    def fake_make_api_bundle(directory, entrypoint, app_mode, environment, extra_files, excludes):
        root = Path(directory)
        observed["files"] = sorted(path.name for path in root.iterdir())
        observed["requirements"] = (root / "requirements.txt").read_text(encoding="utf-8")
        observed["wrapper"] = (root / "runner.py").read_text(encoding="utf-8")
        observed["directory"] = directory
        observed["entrypoint"] = entrypoint
        observed["app_mode"] = app_mode
        observed["environment"] = environment
        observed["extra_files"] = extra_files
        observed["excludes"] = excludes
        return io.BytesIO(b"bundle")

    with patch(
        "posit_cli.connect.run.Environment.create_python_environment",
        return_value="environment",
    ), patch("posit_cli.connect.run.make_api_bundle", side_effect=fake_make_api_bundle):
        bundle = _build_bundle(script, ("arg",), "python3.12")

    assert bundle.read() == b"bundle"
    assert observed["entrypoint"] == "runner:app"
    assert observed["app_mode"] is AppModes.PYTHON_API
    assert observed["environment"] == "environment"
    assert observed["extra_files"] == []
    assert observed["excludes"] == []
    assert observed["requirements"] == ""
    assert "from flask" not in observed["wrapper"]


def test_build_r_bundle_uses_rpy2_python_manifest(tmp_path):
    script = tmp_path / "hello.R"
    script.write_text('cat("hello from R\\n")\n', encoding="utf-8")

    bundle = _build_r_bundle(script, ("arg",), "r4.5")
    with tarfile.open(fileobj=bundle, mode="r:gz") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        assert sorted(archive.getnames()) == [
            "__posit_connect_run_program.R",
            "manifest.json",
            "pyproject.toml",
            "requirements.txt",
            "runner.py",
        ]
        assert manifest["metadata"]["appmode"] == "python-api"
        assert manifest["metadata"]["entrypoint"] == "runner:app"
        assert manifest["platform"] == "4.5"
        assert manifest["packages"] == {}
        assert manifest["environment"]["python"]["requires"] == ">=3.8"
        assert (
            archive.extractfile("pyproject.toml").read().decode()
            == '[project]\nname = "posit-connect-run"\nversion = "0.0.0"\nrequires-python = ">=3.8"\n'
        )
        assert archive.extractfile("requirements.txt").read().decode() == "rpy2\n"
        assert 'PROGRAM_ARGS = ["arg"]' in archive.extractfile("runner.py").read().decode()


def test_build_r_bundle_defaults_to_local_r_version(tmp_path):
    script = tmp_path / "hello.R"
    script.write_text('cat("hello from R\\n")\n', encoding="utf-8")

    with patch("posit_cli.connect.run._local_r_runtime_version", return_value="4.5"):
        bundle = _build_r_bundle(script, (), None)

    with tarfile.open(fileobj=bundle, mode="r:gz") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))

    assert manifest["platform"] == "4.5"
