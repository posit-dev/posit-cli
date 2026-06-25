"""``posit connect api`` -- a ``gh api``-style raw REST client for Connect.

Backed by rsconnect-python's authenticated client (``RSConnectExecutor`` ->
``RSConnectClient``), so it reuses the same credential store, transparently
picks OAuth ``Bearer`` vs API-``Key`` auth, and auto-refreshes OAuth tokens on
401 -- no separate auth glue needed.
"""

import json
import sys
from typing import Any, Dict, List, Optional, Tuple

import click
from rsconnect.api import RSConnectExecutor, RSConnectException


def _read_at_value(raw: str) -> str:
    """Resolve a ``@file`` / ``@-`` (stdin) field value, gh-style."""
    source = raw[1:]
    if source == "-":
        return sys.stdin.read()
    with open(source, encoding="utf-8") as f:
        return f.read()


def _parse_typed(value: str) -> Any:
    """Parse a ``-F`` typed field value (true/false/null/number/@file/string)."""
    if value.startswith("@"):
        return _read_at_value(value)
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _split_pairs(pairs: Tuple[str, ...], *, typed: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise click.BadParameter(
                f"expected key=value, got {pair!r}",
                param_hint="--field/--raw-field",
            )
        key, value = pair.split("=", 1)
        out[key] = _parse_typed(value) if typed else value
    return out


def _split_headers(headers: Tuple[str, ...]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for header in headers:
        if ":" not in header:
            raise click.BadParameter(
                f"expected key:value, got {header!r}", param_hint="--header"
            )
        key, value = header.split(":", 1)
        out[key.strip()] = value.strip()
    return out


@click.command(
    "api",
    short_help="Make an authenticated request to the Connect API.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument("path")
@click.option(
    "--method",
    "-X",
    default=None,
    help="HTTP method. Defaults to GET, or POST when fields/input are given.",
)
@click.option(
    "--field",
    "-F",
    "typed_fields",
    multiple=True,
    metavar="key=value",
    help="Add a typed parameter (true/false/null/numbers; @file reads a file, @- reads stdin).",
)
@click.option(
    "--raw-field",
    "-f",
    "raw_fields",
    multiple=True,
    metavar="key=value",
    help="Add a string parameter.",
)
@click.option(
    "--header",
    "-H",
    "headers",
    multiple=True,
    metavar="key:value",
    help="Add a request header.",
)
@click.option(
    "--input",
    "input_body",
    metavar="FILE",
    help="Read the raw request body from a file ('-' for stdin).",
)
# Credential selection -- mirrors rsconnect's own options/precedence.
@click.option("--name", "-n", default=None, help="Nickname of a saved server.")
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
    "--insecure",
    "-i",
    is_flag=True,
    default=False,
    envvar="CONNECT_INSECURE",
    help="Disable TLS certificate verification.",
)
@click.option(
    "--cacert",
    "-c",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    envvar="CONNECT_CA_CERTIFICATE",
    help="Path to trusted TLS CA certificate.",
)
def api(
    path: str,
    method: Optional[str],
    typed_fields: Tuple[str, ...],
    raw_fields: Tuple[str, ...],
    headers: Tuple[str, ...],
    input_body: Optional[str],
    name: Optional[str],
    server: Optional[str],
    api_key: Optional[str],
    insecure: bool,
    cacert: Optional[str],
) -> None:
    """Make an authenticated request to a Connect API endpoint and print the JSON response.

    PATH is relative to the Connect API root, e.g. 'v1/content' or 'v1/user'
    (the '/__api__' prefix is added for you). Behaves like 'gh api'.

    Examples:

      posit connect api v1/user

      posit connect api v1/content -X POST -f name=my-app

      posit connect api v1/content -F count=10
    """
    fields: Dict[str, Any] = {}
    fields.update(_split_pairs(raw_fields, typed=False))
    fields.update(_split_pairs(typed_fields, typed=True))

    raw_body = _read_at_value("@" + input_body) if input_body else None
    if raw_body is not None and fields:
        raise click.UsageError("--input cannot be combined with -f/-F fields.")

    has_payload = bool(fields) or raw_body is not None
    resolved_method = (method or ("POST" if has_payload else "GET")).upper()

    query_params: Optional[Dict[str, Any]] = None
    body: Any = None
    if raw_body is not None:
        body = raw_body
    elif fields:
        if resolved_method == "GET":
            query_params = fields
        else:
            body = fields

    request_headers = _split_headers(headers) or None

    try:
        ce = RSConnectExecutor(
            ctx=None,
            name=name,
            url=server,
            api_key=api_key,
            insecure=insecure,
            cacert=cacert,
        )
        ce.setup_client()
        result = ce.client.request(
            resolved_method,
            path.lstrip("/"),  # client prepends /__api__ itself
            query_params=query_params,
            body=body,
            headers=request_headers,
        )
    except RSConnectException as exc:
        raise click.ClickException(str(exc)) from exc

    _emit(result)


def _emit(result: Any) -> None:
    """Print a 2xx JSON body, or surface a non-2xx HTTPResponse and exit non-zero."""
    if isinstance(result, (dict, list)):
        click.echo(_dumps(result))
        return

    # Non-2xx (or transport error): rsconnect returns an HTTPResponse object
    # carrying status/reason and a json_data or raw response_body.
    status = getattr(result, "status", None)
    reason = getattr(result, "reason", None)
    exception = getattr(result, "exception", None)
    payload = getattr(result, "json_data", None)
    if payload is None:
        payload = getattr(result, "response_body", None)

    if status is not None:
        header = f"HTTP {status} {reason or ''}".rstrip()
    elif exception is not None:
        header = f"request failed: {exception}"
    else:
        # Not an HTTPResponse we recognize -- fall back to printing it.
        click.echo(_dumps(result))
        return

    body = _dumps(payload) if payload not in (None, "") else ""
    click.echo(f"{header}\n{body}".rstrip(), err=True)
    raise SystemExit(1)


def _dumps(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return str(value)
