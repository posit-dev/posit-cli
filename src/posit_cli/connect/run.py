"""``posit connect run`` -- execute a Python or R program through Connect content."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Optional, Tuple

import click
from rsconnect.api import RSConnectException, RSConnectExecutor
from rsconnect.bundle import make_api_bundle
from rsconnect.environment import Environment
from rsconnect.environment_r import REnvironment
from rsconnect.http_support import HTTPResponse, HTTPServer
from rsconnect.models import AppModes


_RPY2_REQUIREMENT = "rpy2"
_PYTHON_PROJECT_METADATA = """\
[project]
name = "posit-connect-run"
version = "0.0.0"
requires-python = ">=3.8"
"""


def _python_runtime_version(runtime: Optional[str]) -> Optional[str]:
    """Translate ``python`` or ``pythonX.Y`` into a manifest version."""
    if runtime is None or runtime == "python":
        return None
    if not runtime.startswith("python"):
        raise click.BadParameter(
            "runtime must be 'python' or a Python version such as 'python3.12'",
            param_hint="--runtime",
        )

    version = runtime[len("python") :]
    if not version or any(not (character.isdigit() or character == ".") for character in version):
        raise click.BadParameter(
            "runtime must be 'python' or a Python version such as 'python3.12'",
            param_hint="--runtime",
        )
    return version


def _r_runtime_version(runtime: Optional[str]) -> Optional[str]:
    """Translate ``r`` or ``rX.Y`` into an R manifest version."""
    if runtime is None or runtime.lower() == "r":
        return None
    if not runtime.lower().startswith("r"):
        raise click.BadParameter(
            "runtime must be 'r' or an R version such as 'r4.5'",
            param_hint="--runtime",
        )

    version = runtime[1:]
    if not version or any(not (character.isdigit() or character == ".") for character in version):
        raise click.BadParameter(
            "runtime must be 'r' or an R version such as 'r4.5'",
            param_hint="--runtime",
        )
    return version


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


def _wrapper_source(program_args: Tuple[str, ...]) -> str:
    """Create the small WSGI adapter used by the legacy content API."""
    encoded_args = json.dumps(list(program_args))
    return f"""\
import os
import subprocess
import sys

PROGRAM = "__posit_connect_run_program.py"
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


def _rpy2_wrapper_source(program_args: Tuple[str, ...]) -> str:
    """Create the WSGI adapter that evaluates the R program through rpy2."""
    encoded_args = json.dumps(list(program_args))
    return f'''\
import contextlib
import io

PROGRAM = "__posit_connect_run_program.R"
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


def _build_python_bundle(
    path: Path,
    program_args: Tuple[str, ...],
    runtime: Optional[str],
) -> BinaryIO:
    """Build a normal Python API bundle containing the program and adapter."""
    with tempfile.TemporaryDirectory(prefix="posit-connect-run-") as directory:
        root = Path(directory)
        (root / "__posit_connect_run_program.py").write_bytes(path.read_bytes())
        (root / "runner.py").write_text(_wrapper_source(program_args), encoding="utf-8")
        (root / "pyproject.toml").write_text(_PYTHON_PROJECT_METADATA, encoding="utf-8")
        (root / "requirements.txt").write_text("", encoding="utf-8")

        environment = Environment.create_python_environment(
            directory,
            override_python_version=_python_runtime_version(runtime),
        )
        return make_api_bundle(
            directory,
            "runner:app",
            AppModes.PYTHON_API,
            environment,
            extra_files=[],
            excludes=[],
        )


def _build_r_bundle(path: Path, program_args: Tuple[str, ...], runtime: Optional[str]) -> BinaryIO:
    """Build a Python API bundle that runs the R program through rpy2."""
    with tempfile.TemporaryDirectory(prefix="posit-connect-run-") as directory:
        root = Path(directory)
        (root / "__posit_connect_run_program.R").write_bytes(path.read_bytes())
        (root / "runner.py").write_text(_rpy2_wrapper_source(program_args), encoding="utf-8")
        (root / "pyproject.toml").write_text(_PYTHON_PROJECT_METADATA, encoding="utf-8")
        (root / "requirements.txt").write_text(f"{_RPY2_REQUIREMENT}\n", encoding="utf-8")

        environment = Environment.create_python_environment(directory)
        r_environment = REnvironment(r_version=_r_manifest_version(runtime), packages={})
        return make_api_bundle(
            directory,
            "runner:app",
            AppModes.PYTHON_API,
            environment,
            extra_files=[],
            excludes=[],
            r_environment=r_environment,
        )


def _build_bundle(path: Path, program_args: Tuple[str, ...], runtime: Optional[str]) -> BinaryIO:
    if path.suffix.lower() == ".r":
        return _build_r_bundle(path, program_args, runtime)
    return _build_python_bundle(path, program_args, runtime)


def _content_name(path: Path, job_name: Optional[str]) -> str:
    if job_name:
        return job_name
    return f"posit-connect-run-{path.stem}-{uuid.uuid4().hex[:12]}"


def _wait_for_deployment(client: Any, deployment: Any) -> None:
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


def _content_response(client: Any, content_url: str) -> HTTPResponse:
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


def _delete_content(client: Any, content_guid: str) -> None:
    response = client.delete(f"v1/content/{content_guid}", decode_response=False)
    if isinstance(response, HTTPResponse):
        if response.exception:
            raise RSConnectException(str(response.exception))
        if not 200 <= response.status < 300:
            raise RSConnectException(f"HTTP {response.status} {response.reason}".rstrip())


@click.command(
    "run",
    short_help="Run a Python or R program through a temporary Connect API.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument(
    "path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.argument("program_args", nargs=-1, type=click.UNPROCESSED)
@click.option(
    "--profile",
    default="standard",
    show_default=True,
    help="Dispatch profile. The legacy compatibility path supports standard only.",
)
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
    program_args: Tuple[str, ...],
    profile: str,
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

    PATH must be a single ``.py`` or ``.R`` source file. Arguments after ``--``
    are passed to the submitted program.
    """
    suffix = path.suffix.lower()
    if suffix not in {".py", ".r"}:
        raise click.BadParameter(
            "PATH must be a Python or R file ending in .py or .R",
            param_hint="PATH",
        )
    if profile != "standard":
        raise click.BadParameter(
            "the legacy compatibility path supports only the 'standard' profile",
            param_hint="--profile",
        )
    if suffix == ".py":
        _python_runtime_version(runtime)
    else:
        _r_runtime_version(runtime)

    executor: Optional[RSConnectExecutor] = None
    content_guid: Optional[str] = None
    try:
        executor = RSConnectExecutor(
            ctx=None,
            name=server_name,
            url=server,
            api_key=api_key,
            insecure=insecure,
            cacert=cacert,
        )
        executor.setup_client()

        client = executor.client
        content = client.content_create(_content_name(path, job_name))
        content_guid = content.get("guid") if isinstance(content, dict) else None
        content_url = content.get("content_url") if isinstance(content, dict) else None
        if not isinstance(content_guid, str) or not content_guid:
            raise click.ClickException("Connect returned no content GUID.")
        if not isinstance(content_url, str) or not content_url:
            raise click.ClickException("Connect returned no content URL.")

        bundle = _build_bundle(path, program_args, runtime)
        uploaded = client.upload_bundle(content_guid, bundle)
        bundle_id = uploaded.get("id") if isinstance(uploaded, dict) else None
        if not isinstance(bundle_id, str) or not bundle_id:
            raise click.ClickException("Connect returned no bundle ID.")

        deployment = client.content_deploy(content_guid, bundle_id=bundle_id)
        _wait_for_deployment(client, deployment)

        if detach:
            click.echo(content_url)
            return

        response = _content_response(client, content_url)
        _emit_response(response)
        if response.exception:
            raise click.ClickException(f"running content failed: {response.exception}")
        if not 200 <= response.status < 300:
            raise click.exceptions.Exit(1)
    except RSConnectException as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if content_guid and not detach and executor is not None:
            try:
                _delete_content(executor.client, content_guid)
            except Exception as exc:
                click.echo(
                    f"Warning: unable to delete temporary content {content_guid}: {exc}",
                    err=True,
                )
