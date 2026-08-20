"""``posit connect run`` -- execute a Python or R program through Connect content."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Optional, Protocol, Tuple

import click
from rsconnect.api import RSConnectException, RSConnectExecutor
from rsconnect.bundle import make_api_bundle
from rsconnect.environment import Environment
from rsconnect.environment_r import REnvironment
from rsconnect.http_support import HTTPResponse, HTTPServer
from rsconnect.models import AppModes


_RPY2_REQUIREMENT = "rpy2"
_PYTHON_PROGRAM_FILENAME = "__posit_connect_run_program.py"
_R_PROGRAM_FILENAME = "__posit_connect_run_program.R"
_RUNNER_FILENAME = "runner.py"
_RUNNER_ENTRYPOINT = "runner:app"
_DIRECTORY_RUNNER_FILENAME = "__posit_connect_run_runner.py"
_PYTHON_PROJECT_METADATA = """\
[project]
name = "posit-connect-run"
version = "0.0.0"
requires-python = ">=3.8"
"""
_PYTHON_ENTRYPOINT_NAMES = {"__main__.py", "main.py", "app.py"}
_R_ENTRYPOINT_NAMES = {"main.r", "app.r"}
_SUPPORTED_SOURCE_SUFFIXES = {".py", ".r"}

ProgramArguments = Tuple[str, ...]


class _ConnectClient(Protocol):
    """The subset of the Connect client used by the run operation."""

    def content_create(self, name: str) -> object: ...

    def upload_bundle(self, content_guid: str, bundle: BinaryIO) -> object: ...

    def content_deploy(self, content_guid: str, *, bundle_id: str) -> object: ...

    def wait_for_task(
        self,
        task_id: str,
        *,
        log_callback: Optional[Callable[..., object]],
        raise_on_error: bool,
    ) -> Tuple[object, object]: ...

    def delete(self, path: str, *, decode_response: bool) -> object: ...


class _ConnectExecutor(Protocol):
    client: _ConnectClient

BundleBuilder = Callable[[Path, ProgramArguments, Optional[str]], BinaryIO]
ExecutorFactory = Callable[..., _ConnectExecutor]
ContentInvoker = Callable[[_ConnectClient, str], HTTPResponse]
ContentDeleter = Callable[[_ConnectClient, str], None]


@dataclass(frozen=True)
class _RunRequest:
    path: Path
    program_args: ProgramArguments
    runtime: Optional[str]
    job_name: Optional[str]
    detach: bool
    server_name: Optional[str]
    server: Optional[str]
    api_key: Optional[str]
    insecure: bool
    cacert: Optional[str]


@dataclass(frozen=True)
class _RunDependencies:
    executor_factory: ExecutorFactory
    bundle_builder: BundleBuilder
    content_invoker: ContentInvoker
    content_deleter: ContentDeleter


@contextmanager
def _client_connection(client: _ConnectClient) -> Iterator[_ConnectClient]:
    """Reuse rsconnect's HTTP connection across the run lifecycle."""
    if isinstance(client, HTTPServer):
        with client:
            yield client
        return

    # Keep lightweight test doubles and alternate clients usable.
    yield client


def _is_version(value: str) -> bool:
    return bool(value) and all(character.isdigit() or character == "." for character in value)


def _runtime_version(
    runtime: Optional[str],
    *,
    prefix: str,
    description: str,
    case_sensitive: bool,
) -> Optional[str]:
    if runtime is None:
        return None

    normalized_runtime = runtime if case_sensitive else runtime.lower()
    if normalized_runtime == prefix:
        return None
    if not normalized_runtime.startswith(prefix):
        raise click.BadParameter(description, param_hint="--runtime")

    version = runtime[len(prefix) :]
    if not _is_version(version):
        raise click.BadParameter(description, param_hint="--runtime")
    return version


def _python_runtime_version(runtime: Optional[str]) -> Optional[str]:
    """Translate ``python`` or ``pythonX.Y`` into a manifest version."""
    return _runtime_version(
        runtime,
        prefix="python",
        description="runtime must be 'python' or a Python version such as 'python3.12'",
        case_sensitive=True,
    )


def _r_runtime_version(runtime: Optional[str]) -> Optional[str]:
    """Translate ``r`` or ``rX.Y`` into an R manifest version."""
    return _runtime_version(
        runtime,
        prefix="r",
        description="runtime must be 'r' or an R version such as 'r4.5'",
        case_sensitive=False,
    )


def _local_r_runtime_version() -> str:
    executable = shutil.which("Rscript")
    if executable is None:
        raise click.ClickException(
            "Rscript is required to infer the local R version; pass --runtime rX.Y."
        )

    result = subprocess.run(
        [
            executable,
            "--vanilla",
            "-e",
            "cat(paste(R.version$major, R.version$minor, sep = '.'))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    version = result.stdout.strip()
    if (
        result.returncode != 0
        or not version
        or any(not (character.isdigit() or character == ".") for character in version)
    ):
        detail = result.stderr.strip() or "Rscript did not report a version"
        raise click.ClickException(f"unable to determine the local R version: {detail}")
    return version


def _r_manifest_version(runtime: Optional[str]) -> str:
    return _r_runtime_version(runtime) or _local_r_runtime_version()


def _wrapper_source(
    program_args: ProgramArguments,
    program: str = _PYTHON_PROGRAM_FILENAME,
) -> str:
    """Create the small WSGI adapter used by the legacy content API."""
    encoded_args = json.dumps(list(program_args))
    encoded_program = json.dumps(program)
    return f"""\
import os
import subprocess
import sys

PROGRAM = {encoded_program}
PROGRAM_ARGS = {encoded_args}


def app(_environ, start_response):
    result = subprocess.run(
        [sys.executable, PROGRAM, *PROGRAM_ARGS],
        cwd=os.path.dirname(__file__),
        capture_output=True,
        text=True,
        errors="replace",
    )
    output = (result.stdout + result.stderr).encode("utf-8")
    status = "200 OK" if result.returncode == 0 else "500 Internal Server Error"
    start_response(
        status,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(output))),
        ],
    )
    return [output]
"""


def _rpy2_wrapper_source(
    program_args: ProgramArguments,
    program: str = _R_PROGRAM_FILENAME,
) -> str:
    """Create the WSGI adapter that evaluates the R program through rpy2."""
    encoded_args = json.dumps(list(program_args))
    encoded_program = json.dumps(program)
    return f'''\
import contextlib
import io

PROGRAM = {encoded_program}
PROGRAM_ARGS = {encoded_args}


def _run_program():
    import logging

    previous_logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        import rpy2.robjects as robjects

        run_file = robjects.r(
            """
            function(path, args) {{
              execution_env <- new.env(parent = globalenv())
              execution_env[["commandArgs"]] <- function(trailingOnly = FALSE) {{
                if (trailingOnly) args else c("R", "--args", args)
              }}
              oldwd <- getwd()
              on.exit(setwd(oldwd), add = TRUE)
              setwd(dirname(path))
              sys.source(basename(path), envir = execution_env)
            }}
            """
        )
        run_file(PROGRAM, robjects.StrVector(PROGRAM_ARGS))
    finally:
        logging.disable(previous_logging_disable)


def app(_environ, start_response):
    stdout = io.StringIO()
    stderr = io.StringIO()
    status = "200 OK"
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            _run_program()
        except Exception as error:
            status = "500 Internal Server Error"
            stderr.write(f"{{type(error).__name__}}: {{error}}\\n")

    output = (stdout.getvalue() + stderr.getvalue()).encode("utf-8", errors="replace")
    start_response(
        status,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(output))),
        ],
    )
    return [output]
'''


def _runtime_language(runtime: Optional[str]) -> Optional[str]:
    if runtime is None:
        return None
    if runtime.startswith("python"):
        _python_runtime_version(runtime)
        return "python"
    if runtime.lower().startswith("r"):
        _r_runtime_version(runtime)
        return "r"
    raise click.BadParameter(
        "runtime must be a Python or R runtime such as 'python3.12' or 'r4.5'",
        param_hint="--runtime",
    )


def _directory_entrypoint(path: Path, runtime: Optional[str]) -> Path:
    language = _runtime_language(runtime)
    suffixes = {".py", ".r"} if language is None else {".py" if language == "python" else ".r"}
    candidates = sorted(
        (
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() and candidate.suffix.lower() in suffixes
        ),
        key=lambda candidate: candidate.as_posix(),
    )
    if not candidates:
        raise click.BadParameter(
            "PATH directory must contain a runnable Python or R source file.",
            param_hint="PATH",
        )

    entrypoint_names = _PYTHON_ENTRYPOINT_NAMES | _R_ENTRYPOINT_NAMES
    preferred = [
        candidate for candidate in candidates if candidate.name.lower() in entrypoint_names
    ]
    if len(preferred) == 1:
        return preferred[0]
    if len(preferred) > 1:
        raise click.BadParameter(
            "PATH directory contains multiple possible entrypoints; use --runtime "
            "or leave only one of __main__.py, main.py, app.py, main.R, or app.R.",
            param_hint="PATH",
        )
    if len(candidates) == 1:
        return candidates[0]

    raise click.BadParameter(
        "PATH directory must contain one runnable source file or a conventional "
        "entrypoint named __main__.py, main.py, app.py, main.R, or app.R.",
        param_hint="PATH",
    )


def _write_bundle_support_files(
    root: Path,
    wrapper_source: str,
    requirements: str,
    runner_filename: str = _RUNNER_FILENAME,
) -> None:
    (root / runner_filename).write_text(wrapper_source, encoding="utf-8")
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(_PYTHON_PROJECT_METADATA, encoding="utf-8")

    requirements_file = root / "requirements.txt"
    if not requirements_file.exists():
        requirements_file.write_text(requirements, encoding="utf-8")
    elif requirements:
        existing = requirements_file.read_text(encoding="utf-8")
        additions = [
            line
            for line in requirements.splitlines()
            if line and line not in existing.splitlines()
        ]
        if additions:
            separator = "" if existing.endswith("\n") else "\n"
            requirements_file.write_text(
                existing + separator + "\n".join(additions) + "\n",
                encoding="utf-8",
            )


def _write_bundle_files(
    root: Path,
    source_path: Path,
    program_filename: str,
    wrapper_source: str,
    requirements: str,
) -> None:
    (root / program_filename).write_bytes(source_path.read_bytes())
    _write_bundle_support_files(root, wrapper_source, requirements)


def _copy_program_files(
    root: Path,
    path: Path,
    program_filename: str,
    runtime: Optional[str],
) -> str:
    if not path.is_dir():
        (root / program_filename).write_bytes(path.read_bytes())
        return program_filename

    program_path = _directory_entrypoint(path, runtime)
    shutil.copytree(path, root, dirs_exist_ok=True)
    return program_path.relative_to(path).as_posix()


def _directory_runner_filename(root: Path) -> str:
    if not (root / _RUNNER_FILENAME).exists():
        return _RUNNER_FILENAME
    return _DIRECTORY_RUNNER_FILENAME


def _make_api_bundle(
    directory: str,
    environment: object,
    r_environment: Optional[object] = None,
    entrypoint: str = _RUNNER_ENTRYPOINT,
) -> BinaryIO:
    bundle_options = {
        "extra_files": [],
        "excludes": [],
    }
    if r_environment is not None:
        bundle_options["r_environment"] = r_environment

    return make_api_bundle(
        directory,
        entrypoint,
        AppModes.PYTHON_API,
        environment,
        **bundle_options,
    )


def _build_python_bundle(
    path: Path,
    program_args: ProgramArguments,
    runtime: Optional[str],
) -> BinaryIO:
    """Build a normal Python API bundle containing the program and adapter."""
    with tempfile.TemporaryDirectory(prefix="posit-connect-run-") as directory:
        root = Path(directory)
        runner_filename = _RUNNER_FILENAME
        if path.is_dir():
            program = _copy_program_files(root, path, _PYTHON_PROGRAM_FILENAME, runtime)
            runner_filename = _directory_runner_filename(root)
            requirements_file = (
                "pyproject.toml"
                if (root / "pyproject.toml").is_file()
                and not (root / "requirements.txt").is_file()
                else "requirements.txt"
            )
            _write_bundle_support_files(
                root,
                _wrapper_source(program_args, program),
                "",
                runner_filename,
            )
        else:
            requirements_file = "requirements.txt"
            _write_bundle_files(
                root,
                path,
                _PYTHON_PROGRAM_FILENAME,
                _wrapper_source(program_args),
                "",
            )

        if requirements_file == "pyproject.toml":
            environment = Environment.create_python_environment(
                directory,
                requirements_file=requirements_file,
                override_python_version=_python_runtime_version(runtime),
            )
        else:
            environment = Environment.create_python_environment(
                directory,
                override_python_version=_python_runtime_version(runtime),
            )
        entrypoint = f"{Path(runner_filename).stem}:app"
        return _make_api_bundle(directory, environment, entrypoint=entrypoint)


def _build_r_bundle(
    path: Path,
    program_args: ProgramArguments,
    runtime: Optional[str],
) -> BinaryIO:
    """Build a Python API bundle that runs the R program through rpy2."""
    with tempfile.TemporaryDirectory(prefix="posit-connect-run-") as directory:
        root = Path(directory)
        runner_filename = _RUNNER_FILENAME
        if path.is_dir():
            program = _copy_program_files(root, path, _R_PROGRAM_FILENAME, runtime)
            runner_filename = _directory_runner_filename(root)
            _write_bundle_support_files(
                root,
                _rpy2_wrapper_source(program_args, program),
                f"{_RPY2_REQUIREMENT}\n",
                runner_filename,
            )
        else:
            _write_bundle_files(
                root,
                path,
                _R_PROGRAM_FILENAME,
                _rpy2_wrapper_source(program_args),
                f"{_RPY2_REQUIREMENT}\n",
            )

        environment = Environment.create_python_environment(directory)
        r_environment = REnvironment(r_version=_r_manifest_version(runtime), packages={})
        entrypoint = f"{Path(runner_filename).stem}:app"
        return _make_api_bundle(directory, environment, r_environment, entrypoint)


def _build_bundle(path: Path, program_args: ProgramArguments, runtime: Optional[str]) -> BinaryIO:
    program_path = path if path.is_file() else _directory_entrypoint(path, runtime)
    if program_path.suffix.lower() == ".r":
        return _build_r_bundle(path, program_args, runtime)
    return _build_python_bundle(path, program_args, runtime)


def _content_name(path: Path, job_name: Optional[str]) -> str:
    return job_name or f"posit-connect-run-{path.stem}-{uuid.uuid4().hex[:12]}"


def _content_field(content: object, field: str, error_message: str) -> str:
    if not isinstance(content, dict):
        raise click.ClickException(error_message)

    value = content.get(field)
    if not isinstance(value, str) or not value:
        raise click.ClickException(error_message)
    return value


def _deploy_content(
    client: _ConnectClient,
    request: _RunRequest,
    content_guid: str,
    bundle_builder: BundleBuilder,
) -> None:
    bundle = bundle_builder(request.path, request.program_args, request.runtime)
    uploaded = client.upload_bundle(content_guid, bundle)
    bundle_id = _content_field(uploaded, "id", "Connect returned no bundle ID.")
    deployment = client.content_deploy(content_guid, bundle_id=bundle_id)
    _wait_for_deployment(client, deployment)


def _wait_for_deployment(client: _ConnectClient, deployment: object) -> None:
    if not isinstance(deployment, dict):
        raise click.ClickException("Connect returned an invalid deployment response.")

    task_id = deployment.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise click.ClickException("Connect returned no deployment task ID.")

    _, task = client.wait_for_task(task_id, log_callback=None, raise_on_error=False)
    if not isinstance(task, dict):
        raise click.ClickException("Connect returned an invalid deployment task.")

    code = task.get("code", 0)
    if code not in (None, 0):
        detail = task.get("error") or f"deployment exited with status {code}"
        raise click.ClickException(f"deployment failed: {detail}")


def _content_response(client: _ConnectClient, content_url: str) -> HTTPResponse:
    """Invoke the deployed content URL with the same auth and TLS settings."""
    app_server = HTTPServer(
        content_url,
        disable_tls_check=getattr(client, "_disable_tls_check", False),
        ca_data=getattr(client, "_ca_data", None),
        cookies=getattr(client, "_cookies", None),
    )
    app_server._headers.update(getattr(client, "_headers", {}))
    response = app_server.get("", decode_response=False)
    if not isinstance(response, HTTPResponse):
        raise click.ClickException("Connect returned an invalid content response.")
    return response


def _response_text(response: HTTPResponse) -> str:
    value = response.response_body
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _emit_response(response: HTTPResponse) -> None:
    text = _response_text(response)
    if text:
        click.echo(text, nl=not text.endswith("\n"))


def _ensure_successful_response(response: HTTPResponse) -> None:
    if response.exception:
        raise click.ClickException(f"running content failed: {response.exception}")

    status = getattr(response, "status", None)
    if not isinstance(status, int) or not 200 <= status < 300:
        raise click.exceptions.Exit(1)


def _delete_content(client: _ConnectClient, content_guid: str) -> None:
    response = client.delete(f"v1/content/{content_guid}", decode_response=False)
    if isinstance(response, HTTPResponse):
        if response.exception:
            raise RSConnectException(str(response.exception))
        status = getattr(response, "status", None)
        if not isinstance(status, int) or not 200 <= status < 300:
            reason = getattr(response, "reason", "")
            raise RSConnectException(f"HTTP {status} {reason}".rstrip())


def _cleanup_content(
    executor: Optional[_ConnectExecutor],
    content_guid: Optional[str],
    detach: bool,
    content_deleter: ContentDeleter,
) -> None:
    if executor is None or content_guid is None or detach:
        return

    try:
        content_deleter(executor.client, content_guid)
    except Exception as exc:
        # Cleanup is best effort and must not hide the command's result.
        click.echo(
            f"Warning: unable to delete temporary content {content_guid}: {exc}",
            err=True,
        )


def _validate_run_options(path: Path, runtime: Optional[str]) -> None:
    if path.is_dir():
        _directory_entrypoint(path, runtime)
        return

    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED_SOURCE_SUFFIXES:
        raise click.BadParameter(
            "PATH must be a Python or R file ending in .py or .R",
            param_hint="PATH",
        )
    if suffix == ".py":
        _python_runtime_version(runtime)
    else:
        _r_runtime_version(runtime)


def _default_run_dependencies() -> _RunDependencies:
    """Assemble concrete adapters at the CLI composition root."""
    return _RunDependencies(
        executor_factory=RSConnectExecutor,
        bundle_builder=_build_bundle,
        content_invoker=_content_response,
        content_deleter=_delete_content,
    )


def _execute_run(request: _RunRequest, dependencies: _RunDependencies) -> None:
    executor: Optional[_ConnectExecutor] = None
    content_guid: Optional[str] = None
    try:
        executor = dependencies.executor_factory(
            ctx=None,
            name=request.server_name,
            url=request.server,
            api_key=request.api_key,
            insecure=request.insecure,
            cacert=request.cacert,
        )
        client = executor.client
        with _client_connection(client):
            try:
                content = client.content_create(_content_name(request.path, request.job_name))
                content_guid = _content_field(
                    content,
                    "guid",
                    "Connect returned no content GUID.",
                )
                content_url = _content_field(
                    content,
                    "content_url",
                    "Connect returned no content URL.",
                )

                _deploy_content(client, request, content_guid, dependencies.bundle_builder)

                if request.detach:
                    click.echo(content_url)
                    return

                response = dependencies.content_invoker(client, content_url)
                _emit_response(response)
                _ensure_successful_response(response)
            finally:
                _cleanup_content(
                    executor,
                    content_guid,
                    request.detach,
                    dependencies.content_deleter,
                )
    except RSConnectException as exc:
        raise click.ClickException(str(exc)) from exc


@click.command(
    "run",
    short_help="Run a Python or R program through a temporary Connect API.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument(
    "path",
    type=click.Path(
        exists=True,
        file_okay=True,
        dir_okay=True,
        readable=True,
        path_type=Path,
    ),
)
@click.argument("program_args", nargs=-1, type=click.UNPROCESSED)
@click.option(
    "--runtime",
    default=None,
    metavar="NAME",
    help="Runtime, for example python3.12 or r4.5. Defaults to the server runtime.",
)
@click.option("--job-name", default=None, help="Optional name for the temporary content item.")
@click.option(
    "--detach",
    is_flag=True,
    help="Deploy the temporary API and print its URL without invoking or deleting it.",
)
# Credential selection mirrors `posit connect api`.
@click.option("--name", "-n", "server_name", default=None, help="Nickname of a saved server.")
@click.option(
    "--server",
    "-s",
    default=None,
    envvar="CONNECT_SERVER",
    help="Connect server URL [env: CONNECT_SERVER].",
)
@click.option(
    "--api-key",
    "-k",
    default=None,
    envvar="CONNECT_API_KEY",
    help="Connect API key [env: CONNECT_API_KEY].",
)
@click.option(
    "--no-tls-verify",
    "insecure",
    is_flag=True,
    default=False,
    envvar="CONNECT_INSECURE",
    help="Skip TLS certificate verification (still uses TLS) [env: CONNECT_INSECURE].",
)
@click.option(
    "--cacert",
    "-c",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    envvar="CONNECT_CA_CERTIFICATE",
    help="Path to trusted TLS CA certificate.",
)
def run(
    path: Path,
    program_args: ProgramArguments,
    runtime: Optional[str],
    job_name: Optional[str],
    detach: bool,
    server_name: Optional[str],
    server: Optional[str],
    api_key: Optional[str],
    insecure: bool,
    cacert: Optional[str],
) -> None:
    """Run PATH as a Python or R program using Connect's existing content APIs.

    PATH may be a single ``.py`` or ``.R`` source file, or a directory containing
    one runnable source file. Directory entrypoints named ``__main__.py``,
    ``main.py``, ``app.py``, ``main.R``, or ``app.R`` are selected automatically.
    Arguments after ``--`` are passed to the submitted program.
    """
    _validate_run_options(path, runtime)
    request = _RunRequest(
        path=path,
        program_args=program_args,
        runtime=runtime,
        job_name=job_name,
        detach=detach,
        server_name=server_name,
        server=server,
        api_key=api_key,
        insecure=insecure,
        cacert=cacert,
    )
    _execute_run(request, _default_run_dependencies())
