"""End-to-end Publisher workflow against a live Posit Connect instance."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest
from rsconnect.publisher import config
from rsconnect.publisher.record import discover_records, read_record


pytestmark = pytest.mark.integration

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fastapi"


def _connect_credentials():
    server = os.environ.get("CONNECT_SERVER")
    api_key = os.environ.get("CONNECT_API_KEY")
    if not server or not api_key:
        pytest.skip("CONNECT_SERVER and CONNECT_API_KEY are required")
    return server, api_key


def _run_posit(project_dir, home_dir, *args, env_overrides=None):
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    if env_overrides:
        for name, value in env_overrides.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value

    result = subprocess.run(
        [sys.executable, "-m", "posit_cli", *args],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        "posit command failed:\ncommand: {}\nstdout:\n{}\nstderr:\n{}".format(
            " ".join(args), result.stdout, result.stderr
        )
    )
    output_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return output_lines[-1] if output_lines else ""


def _wait_for_json(content_url, api_key, expected_version):
    deadline = time.monotonic() + 120
    last_error = None
    while time.monotonic() < deadline:
        request = Request(
            content_url.rstrip("/") + "/",
            headers={
                "Accept": "application/json",
                "Authorization": "Key {}".format(api_key),
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
            if payload == {
                "service": "posit-cli-fastapi",
                "version": expected_version,
            }:
                return
            last_error = AssertionError("unexpected response: {!r}".format(payload))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(2)

    raise AssertionError(
        "content did not return version {!r}: {}".format(expected_version, last_error)
    )


def _only_record(project_dir):
    paths = discover_records(str(project_dir))
    assert len(paths) == 1, "expected one deployment record, found {!r}".format(paths)
    return read_record(paths[0])


def test_init_and_republish_fastapi(tmp_path):
    server, api_key = _connect_credentials()
    project_dir = tmp_path / "fastapi"
    home_dir = tmp_path / "home"
    shutil.copytree(FIXTURE_DIR, project_dir)
    home_dir.mkdir()

    _run_posit(
        project_dir,
        home_dir,
        "connect",
        "init",
        ".",
        "--type",
        "python-fastapi",
        "--entrypoint",
        "app.py",
        "--title",
        "Posit CLI FastAPI integration",
        "--config",
        "fastapi-integration",
        "--package-file",
        "requirements.txt",
        "--package-manager",
        "uv",
    )

    publisher_config = config.read_config(
        str(project_dir / ".posit" / "publish" / "fastapi-integration.toml")
    )
    assert publisher_config.entrypoint == "app.py"
    assert publisher_config.python == {
        "package_file": "requirements.txt",
        "package_manager": "uv",
    }
    assert "*" in publisher_config.files
    assert "/app.py" in publisher_config.files
    assert "/requirements.txt" in publisher_config.files

    first_url = _run_posit(
        project_dir,
        home_dir,
        "connect",
        "publish",
        ".",
        "--server",
        server,
        "--api-key",
        api_key,
        "--no-metadata",
    )
    assert first_url.startswith(server.rstrip("/") + "/")
    _wait_for_json(first_url, api_key, "one")

    first_record = _only_record(project_dir)
    assert first_record.id
    assert first_record.bundle_id

    app_path = project_dir / "app.py"
    updated_app = app_path.read_text(encoding="utf-8").replace(
        'VERSION = "one"', 'VERSION = "two"'
    )
    assert 'VERSION = "two"' in updated_app
    app_path.write_text(updated_app, encoding="utf-8")

    second_url = _run_posit(
        project_dir,
        home_dir,
        "connect",
        "publish",
        ".",
        "--api-key",
        api_key,
        "--no-metadata",
        env_overrides={"CONNECT_SERVER": None},
    )
    assert second_url == first_url
    _wait_for_json(second_url, api_key, "two")

    second_record = _only_record(project_dir)
    assert second_record.id == first_record.id
    assert second_record.bundle_id
    assert second_record.bundle_id != first_record.bundle_id
