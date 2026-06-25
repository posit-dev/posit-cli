"""Unit tests for `posit connect api` argument handling (no network)."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from posit_cli.__main__ import cli


@pytest.fixture
def runner():
    return CliRunner()


def _invoke(runner, args, request_return=None):
    """Invoke `posit connect api ...` with the rsconnect client mocked.

    Returns (result, request_mock) so tests can assert on the forwarded call.
    """
    with patch("posit_cli.api.RSConnectExecutor") as Executor:
        ce = Executor.return_value
        ce.client.request.return_value = (
            request_return if request_return is not None else {"ok": True}
        )
        result = runner.invoke(cli, ["connect", "api", *args])
        return result, ce.client.request, Executor


def test_get_by_default(runner):
    result, request, _ = _invoke(runner, ["v1/user"])
    assert result.exit_code == 0, result.output
    method, path = request.call_args.args[:2]
    assert method == "GET"
    assert path == "v1/user"  # leading slash stripped; client adds /__api__


def test_leading_slash_stripped(runner):
    _, request, _ = _invoke(runner, ["/v1/user"])
    assert request.call_args.args[1] == "v1/user"


def test_fields_imply_post_and_become_body(runner):
    _, request, _ = _invoke(runner, ["v1/content", "-f", "name=app"])
    assert request.call_args.args[0] == "POST"
    assert request.call_args.kwargs["body"] == {"name": "app"}
    assert request.call_args.kwargs["query_params"] is None


def test_fields_on_get_become_query_params(runner):
    _, request, _ = _invoke(runner, ["v1/content", "-X", "GET", "-f", "q=foo"])
    assert request.call_args.args[0] == "GET"
    assert request.call_args.kwargs["query_params"] == {"q": "foo"}
    assert request.call_args.kwargs["body"] is None


def test_typed_field_parsing(runner):
    _, request, _ = _invoke(
        runner,
        ["v1/content", "-F", "count=10", "-F", "active=true", "-F", "note=hi"],
    )
    body = request.call_args.kwargs["body"]
    assert body == {"count": 10, "active": True, "note": "hi"}


def test_method_override(runner):
    _, request, _ = _invoke(runner, ["v1/content/x", "-X", "delete"])
    assert request.call_args.args[0] == "DELETE"


def test_headers_forwarded(runner):
    _, request, _ = _invoke(runner, ["v1/user", "-H", "X-Test: 1"])
    assert request.call_args.kwargs["headers"] == {"X-Test": "1"}


def test_credential_options_passed_to_executor(runner):
    _, _, Executor = _invoke(
        runner, ["v1/user", "-n", "prod", "-k", "secret", "-s", "https://c.example"]
    )
    kwargs = Executor.call_args.kwargs
    assert kwargs["name"] == "prod"
    assert kwargs["api_key"] == "secret"
    assert kwargs["url"] == "https://c.example"


def test_input_conflicts_with_fields(runner, tmp_path):
    body_file = tmp_path / "b.json"
    body_file.write_text("{}")
    result, _, _ = _invoke(
        runner, ["v1/content", "--input", str(body_file), "-f", "a=b"]
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output


def test_bad_field_format(runner):
    result, _, _ = _invoke(runner, ["v1/user", "-f", "novalue"])
    assert result.exit_code != 0
    assert "key=value" in result.output


def test_non_2xx_response_exits_nonzero(runner):
    err = MagicMock()
    err.status = 404
    err.reason = "Not Found"
    err.exception = None
    err.json_data = {"error": "nope"}
    err.response_body = None
    # MagicMock is neither dict nor list, so _emit treats it as an HTTPResponse.
    result, _, _ = _invoke(runner, ["v1/missing"], request_return=err)
    assert result.exit_code == 1
    assert "HTTP 404 Not Found" in result.output
    assert "nope" in result.output
