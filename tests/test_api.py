"""Unit tests for `posit connect api` argument handling (no network)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from rsconnect.http_support import HTTPResponse

from posit_cli.__main__ import cli


def _http_response(status=None, reason="", body="", content_type="application/json", headers=None):
    """Build a real rsconnect HTTPResponse for a received response.

    Using the real class (not a mock) is deliberate: a previous bug hid behind a
    mock that set attributes the real object only sets conditionally.
    """
    raw = MagicMock()
    raw.status = status
    raw.reason = reason
    raw.version = 11
    raw.getheader.return_value = content_type
    # _header_lines (for --include) iterates the raw response's getheaders().
    raw.getheaders.return_value = list((headers or {"Content-Type": content_type}).items())
    return HTTPResponse("https://example.test/v1", response=raw, body=body)


def _http_exception(exc):
    """Build a real HTTPResponse representing a transport failure (no status)."""
    return HTTPResponse("https://example.test/v1", exception=exc)


@pytest.fixture
def runner():
    return CliRunner()


def _invoke(runner, args, request_return=None):
    """Invoke `posit connect api ...` with the rsconnect client mocked.

    Returns (result, request_mock) so tests can assert on the forwarded call.
    """
    with patch("posit_cli.connect.api.RSConnectExecutor") as Executor:
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
    # Body is pre-encoded JSON (a str), not a dict, so rsconnect doesn't clobber
    # our headers. Content-Type is set for us.
    assert json.loads(request.call_args.kwargs["body"]) == {"name": "app"}
    assert request.call_args.kwargs["query_params"] is None
    assert request.call_args.kwargs["headers"]["Content-Type"] == "application/json"


def test_json_body_preserves_user_headers(runner):
    _, request, _ = _invoke(
        runner, ["v1/content", "-f", "name=app", "-H", "X-Test: 1"]
    )
    headers = request.call_args.kwargs["headers"]
    assert headers["X-Test"] == "1"  # finding 2: must survive a JSON body
    assert headers["Content-Type"] == "application/json"


def test_explicit_content_type_not_overridden(runner):
    _, request, _ = _invoke(
        runner, ["v1/content", "-f", "name=app", "-H", "Content-Type: application/custom"]
    )
    assert request.call_args.kwargs["headers"]["Content-Type"] == "application/custom"


def test_lowercase_content_type_not_duplicated(runner):
    _, request, _ = _invoke(
        runner, ["v1/content", "-f", "name=app", "-H", "content-type: application/custom"]
    )
    headers = request.call_args.kwargs["headers"]
    # No duplicate Content-Type added under a different casing.
    ct_keys = [k for k in headers if k.lower() == "content-type"]
    assert ct_keys == ["content-type"]
    assert headers["content-type"] == "application/custom"


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
    assert json.loads(request.call_args.kwargs["body"]) == {
        "count": 10,
        "active": True,
        "note": "hi",
    }


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


def test_jq_extracts_scalar_unquoted(runner):
    result, _, _ = _invoke(runner, ["v1/user", "-q", ".username"], request_return={"username": "neal"})
    assert result.exit_code == 0, result.output
    # gh-style: a string result prints raw, without surrounding quotes.
    assert result.output.strip() == "neal"


def test_jq_object_result_is_compact_json(runner):
    result, _, _ = _invoke(
        runner, ["v1/user", "--jq", "{u: .username}"], request_return={"username": "neal"}
    )
    assert result.output.strip() == '{"u": "neal"}'


def test_jq_stream_prints_one_per_line(runner):
    result, _, _ = _invoke(
        runner,
        ["v1/content", "-q", ".[].name"],
        request_return=[{"name": "a"}, {"name": "b"}],
    )
    assert result.output.split() == ["a", "b"]


def test_invalid_jq_fails_before_request(runner):
    result, request, _ = _invoke(runner, ["v1/user", "-q", ".["])
    assert result.exit_code != 0
    assert "--jq" in result.output
    # Fail fast: a bad expression must not reach the network.
    assert not request.called


def test_jq_runtime_error_is_clean_not_traceback(runner):
    # Compiles fine, fails at evaluation time -- must surface as a clean CLI
    # error (exit 1), not an unhandled ValueError traceback.
    result, _, _ = _invoke(
        runner, ["v1/user", "-q", 'error("boom")'], request_return={"username": "neal"}
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "jq:" in result.output


def test_jq_not_applied_to_error_response(runner):
    err = _http_response(status=404, reason="Not Found", body=json.dumps({"error": "nope"}))
    result, _, _ = _invoke(runner, ["v1/missing", "-q", ".error"], request_return=err)
    # Errors are surfaced verbatim on stderr, never filtered through jq.
    assert result.exit_code == 1
    assert "HTTP 404 Not Found" in result.output
    assert "nope" in result.output


def test_include_prints_status_line_and_headers(runner):
    resp = _http_response(
        status=200,
        reason="OK",
        body=json.dumps({"username": "neal"}),
        headers={"Content-Type": "application/json", "X-Connect": "1"},
    )
    result, _, _ = _invoke(runner, ["v1/user", "-i"], request_return=resp)
    assert result.exit_code == 0, result.output
    assert "HTTP/1.1 200 OK" in result.output
    assert "X-Connect: 1" in result.output
    # Body still follows the headers.
    assert '"username": "neal"' in result.output


def test_include_bypasses_tweak_response(runner):
    # --include must neutralize RSConnectClient's 2xx-JSON unwrapping so the raw
    # HTTPResponse (with status/headers) comes back.
    with patch("posit_cli.connect.api.RSConnectExecutor") as Executor:
        ce = Executor.return_value
        ce.client.request.return_value = _http_response(
            status=200, reason="OK", body=json.dumps({"ok": True})
        )
        result = runner.invoke(cli, ["connect", "api", "v1/user", "-i"])
    assert result.exit_code == 0, result.output
    # The identity override was installed on the client.
    assert ce.client._tweak_response("x") == "x"


def test_include_with_jq_filters_body_after_headers(runner):
    resp = _http_response(status=200, reason="OK", body=json.dumps({"username": "neal"}))
    result, _, _ = _invoke(runner, ["v1/user", "-i", "-q", ".username"], request_return=resp)
    assert "HTTP/1.1 200 OK" in result.output
    assert "neal" in result.output


def test_include_on_error_still_exits_nonzero(runner):
    resp = _http_response(status=404, reason="Not Found", body=json.dumps({"error": "nope"}))
    result, _, _ = _invoke(runner, ["v1/missing", "-i"], request_return=resp)
    assert result.exit_code == 1
    assert "HTTP/1.1 404 Not Found" in result.output
    assert "nope" in result.output


def test_include_jq_runtime_error_leaks_nothing_to_stdout(runner):
    # A jq runtime failure on a 2xx response must abort before emitting headers,
    # so a failed command never leaks partial output (headers) to stdout.
    resp = _http_response(status=200, reason="OK", body=json.dumps({"username": "neal"}))
    with patch("posit_cli.connect.api.RSConnectExecutor") as Executor:
        ce = Executor.return_value
        ce.client.request.return_value = resp
        result = runner.invoke(
            cli, ["connect", "api", "v1/user", "-i", "-q", 'error("boom")']
        )
    assert result.exit_code != 0
    assert result.stdout == ""  # no headers, no body
    assert "jq:" in result.stderr


def test_no_tls_verify_flag_sets_insecure(runner):
    # We deliberately renamed rsconnect's --insecure to --no-tls-verify (and
    # dropped -i, reserving it for a future gh-style --include). Guard the wiring.
    _, _, Executor = _invoke(runner, ["v1/user", "--no-tls-verify"])
    assert Executor.call_args.kwargs["insecure"] is True


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
    err = _http_response(status=404, reason="Not Found", body=json.dumps({"error": "nope"}))
    result, _, _ = _invoke(runner, ["v1/missing"], request_return=err)
    assert result.exit_code == 1
    assert "HTTP 404 Not Found" in result.output
    assert "nope" in result.output


def test_implicit_post_4xx_hints_query_params(runner):
    # gh parity: bare -f implies POST. When that POST 4xxs, nudge toward query
    # params (the common cause is using -f to filter a read).
    err = _http_response(status=400, reason="Bad Request", body=json.dumps({"error": "unknown field"}))
    result, _, _ = _invoke(runner, ["v1/content", "-f", "limit=2"], request_return=err)
    assert result.exit_code == 1
    assert "-X GET" in result.output
    assert "?key=value" in result.output


def test_explicit_method_4xx_omits_hint(runner):
    # If the user chose the method, the implicit-POST hint would be noise.
    err = _http_response(status=400, reason="Bad Request", body=json.dumps({"error": "nope"}))
    result, _, _ = _invoke(runner, ["v1/content", "-X", "POST", "-f", "name=x"], request_return=err)
    assert result.exit_code == 1
    assert "query parameters" not in result.output


def test_implicit_post_5xx_omits_hint(runner):
    # A server error isn't the user's field/method mistake; don't misdirect them.
    err = _http_response(status=500, reason="Server Error", body="")
    result, _, _ = _invoke(runner, ["v1/content", "-f", "limit=2"], request_return=err)
    assert result.exit_code == 1
    assert "query parameters" not in result.output


def test_2xx_no_content_is_success(runner):
    # finding 1: a 204 comes back as an HTTPResponse with no JSON body; it must
    # be treated as success, not an error.
    resp = _http_response(status=204, reason="No Content", body="")
    result, _, _ = _invoke(runner, ["v1/content/x", "-X", "DELETE"], request_return=resp)
    assert result.exit_code == 0, result.output
    assert result.output.strip() == ""


def test_transport_exception_exits_nonzero(runner):
    resp = _http_exception(OSError("boom"))
    result, _, _ = _invoke(runner, ["v1/user"], request_return=resp)
    assert result.exit_code == 1
    assert "request failed: boom" in result.output
