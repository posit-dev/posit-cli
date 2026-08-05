"""``posit connect api`` -- a ``gh api``-style raw REST client for Connect.

Backed by rsconnect-python's authenticated client (``RSConnectExecutor`` ->
``RSConnectClient``), so it reuses the same credential store, transparently
picks OAuth ``Bearer`` vs API-``Key`` auth, and auto-refreshes OAuth tokens on
401 -- no separate auth glue needed.
"""

import json
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlparse

import click
import jq
from rsconnect.api import RSConnectExecutor, RSConnectException
from rsconnect.http_support import HTTPResponse

# Safety cap so a malformed/cyclic paging.next can't loop forever.
_MAX_PAGES = 10_000
# Connect's maximum page size; request it for follow-up pages to minimize
# round-trips (matches posit-sdk-py).
_MAX_PAGE_SIZE = 500


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
            raise click.BadParameter(f"expected key:value, got {header!r}", param_hint="--header")
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
@click.option(
    "--jq",
    "-q",
    "jq_filter",
    default=None,
    metavar="EXPR",
    help="Filter the JSON response through a jq expression (like 'gh api --jq').",
)
@click.option(
    "--include",
    "-i",
    is_flag=True,
    default=False,
    help="Include the HTTP response status line and headers in the output.",
)
@click.option(
    "--paginate",
    is_flag=True,
    default=False,
    help="Follow Connect's pagination and output all pages' results combined (GET only).",
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
def api(
    path: str,
    method: Optional[str],
    typed_fields: Tuple[str, ...],
    raw_fields: Tuple[str, ...],
    headers: Tuple[str, ...],
    input_body: Optional[str],
    jq_filter: Optional[str],
    include: bool,
    paginate: bool,
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

      posit connect api v1/user -q .username

      posit connect api v1/content -X POST -f name=my-app

      posit connect api v1/content -F count=10
    """
    fields: Dict[str, Any] = {}
    fields.update(_split_pairs(raw_fields, typed=False))
    fields.update(_split_pairs(typed_fields, typed=True))

    raw_body = _read_at_value("@" + input_body) if input_body else None
    if raw_body is not None and fields:
        raise click.UsageError("--input cannot be combined with -f/-F fields.")

    # Compile the jq filter up front so a typo fails before we hit the network.
    jq_program = None
    if jq_filter is not None:
        try:
            jq_program = jq.compile(jq_filter)
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--jq") from exc

    has_payload = bool(fields) or raw_body is not None
    resolved_method = (method or ("POST" if has_payload else "GET")).upper()

    if paginate:
        # Pagination walks read endpoints and combines bodies; showing the
        # headers of just one of N responses would be misleading, and following
        # pages of a write makes no sense.
        if include:
            raise click.UsageError("--paginate cannot be combined with --include.")
        if resolved_method != "GET":
            raise click.UsageError("--paginate only supports GET requests.")

    request_headers = _split_headers(headers)

    query_params: Optional[Dict[str, Any]] = None
    body: Any = None
    if raw_body is not None:
        body = raw_body
    elif fields:
        if resolved_method == "GET":
            query_params = fields
        else:
            # Encode the JSON body ourselves rather than handing rsconnect a dict:
            # when given a Mapping/list, RSConnectClient.request *replaces* the
            # headers with just Content-Type, dropping any user -H values. Passing
            # an already-encoded str keeps our headers intact.
            body = json.dumps(fields)
            # Only default Content-Type if the user didn't set it under any casing;
            # a case-sensitive setdefault would emit a duplicate header.
            if not any(k.lower() == "content-type" for k in request_headers):
                request_headers["Content-Type"] = "application/json"

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
        request_path = _resolve_path(path, getattr(ce.remote_server, "url", None))
        if include:
            # RSConnectClient._tweak_response unwraps a 2xx JSON body to a
            # dict/list, discarding the status line and headers. To show them we
            # need the raw HTTPResponse, so neutralize the unwrapping for this
            # request (the identity is exactly the HTTPServer base behavior).
            ce.client._tweak_response = lambda response: response
        if paginate:
            result = _request_all_pages(
                ce.client, resolved_method, request_path, query_params, body, request_headers
            )
        else:
            result = ce.client.request(
                resolved_method,
                request_path,
                query_params=query_params,
                body=body,
                headers=request_headers,
            )
    except RSConnectException as exc:
        raise click.ClickException(str(exc)) from exc

    # Like gh, bare -f/-F fields imply POST and are sent as a JSON body. A common
    # mistake is reaching for them to filter a GET list, which Connect rejects as
    # an unknown body field. Only when the POST was *implicit* (no -X) does a 4xx
    # warrant nudging the user toward query params.
    fields_implied_post = method is None and bool(fields)
    _emit(result, jq_program, query_param_hint=fields_implied_post, include=include)


def _emit(
    result: Any,
    jq_program: Any = None,
    query_param_hint: bool = False,
    include: bool = False,
) -> None:
    """Print the response body, or surface an error and exit non-zero.

    RSConnectClient unwraps a 2xx JSON body to a dict/list/scalar, but returns a
    raw ``HTTPResponse`` for any other case -- including *successful* responses
    with no JSON body (e.g. 204 No Content) as well as actual errors. So a bare
    ``HTTPResponse`` must be classified by status, not treated as failure.

    ``jq_program`` (when given) filters a *successful* JSON body before printing;
    error responses are never filtered. ``query_param_hint`` adds a nudge toward
    query params when an implicit-POST request fails with a client error.
    ``include`` prepends the HTTP status line and response headers (requires the
    raw HTTPResponse, which the caller arranges by bypassing _tweak_response).
    """
    if isinstance(result, HTTPResponse):
        # status/reason/headers are only present when an actual response arrived;
        # on a transport exception they're absent entirely.
        status = getattr(result, "status", None)
        payload = result.json_data if result.json_data is not None else result.response_body
    else:
        # Already-decoded 2xx JSON body (the unwrapped, non-include path).
        status = 200
        payload = result

    success = status is not None and 200 <= status < 300

    if success:
        # Render the body (running jq) *before* emitting anything: a jq runtime
        # failure must abort with nothing on stdout, not leak the headers first.
        rendered = _render_success(payload, jq_program)
        if include:
            for line in _header_lines(result, status):
                click.echo(line)
            click.echo("")  # blank line between headers and body
        if rendered is not None:
            click.echo(rendered)
        return

    # Failure: in include mode the status line + headers go to stderr too,
    # matching our errors-to-stderr rule.
    if include and status is not None:
        for line in _header_lines(result, status):
            click.echo(line, err=True)
        click.echo("", err=True)

    if status is None:
        # Transport failure: no response or headers exist (include is moot here).
        message = (
            f"request failed: {result.exception}"
            if result.exception is not None
            else "request failed"
        )
    elif include:
        # The status line and headers were already shown; just the body here.
        message = _dumps(payload) if payload not in (None, "") else ""
    else:
        header = f"HTTP {status} {getattr(result, 'reason', '') or ''}".rstrip()
        body = _dumps(payload) if payload not in (None, "") else ""
        message = f"{header}\n{body}".rstrip()

    if query_param_hint and status is not None and 400 <= status < 500:
        message += (
            "\n\nNote: -f/-F fields were sent as a JSON body (they imply POST). "
            "For query parameters on a read, use '-X GET' or put them in the "
            'path: api "<path>?key=value".'
        )
    if message:
        click.echo(message, err=True)
    raise SystemExit(1)


def _request_all_pages(
    client: Any,
    method: str,
    path: str,
    query_params: Optional[Dict[str, Any]],
    body: Any,
    headers: Dict[str, str],
) -> Any:
    """Fetch every page of a Connect list endpoint and combine the results.

    Connect paginates two ways (mirrored from posit-sdk-py's Paginator and
    CursorPaginator):

    * cursor style -- ``{paging: {cursors: {next}}, results}`` (e.g. audit logs):
      follow the ``paging.cursors.next`` token until it's empty.
    * page-number style -- ``{current_page, total, results}`` (e.g. users,
      groups): request ``page_number`` 1..N until results are empty or the
      accumulated count reaches ``total``.

    Anything else (a bare array, an unrecognized shape) is treated as a single
    page. Returns the combined result, or the first ``HTTPResponse`` (an error
    or non-JSON body) so the caller's error path handles it.
    """
    base_path, params = _split_query(path, query_params)
    pages: List[Any] = []
    count = 0
    while True:
        result = client.request(
            method, base_path, query_params=(params or None), body=body, headers=headers
        )
        if isinstance(result, HTTPResponse):
            # Non-2xx or non-JSON: surface it directly (errors aren't paged).
            return result
        pages.append(result)

        paging = result.get("paging") if isinstance(result, dict) else None
        results = result.get("results") if isinstance(result, dict) else None

        # Work out the next request, or None to stop.
        next_target: Optional[Tuple[str, Dict[str, Any]]] = None
        if isinstance(paging, dict):
            # Cursor style: prefer the cursor token; fall back to the full
            # paging.next URL if an endpoint only provides that form. A cursor is
            # a position token, so raising the page size between pages is safe.
            cursors = paging.get("cursors") or {}
            token = cursors.get("next")
            if token:
                next_params = {**params, "next": token}
                next_params.setdefault("limit", _MAX_PAGE_SIZE)
                next_target = (base_path, next_params)
            else:
                next_url = paging.get("next")
                if isinstance(next_url, str) and next_url:
                    next_target = _split_query(_next_page_path(next_url), None)
        elif isinstance(results, list) and isinstance(result.get("current_page"), int):
            # Page-number style: stop on an empty page or once we've seen `total`.
            # Page size must stay *constant* across requests -- it defines the
            # offset window, so changing it mid-stream would skip/duplicate rows.
            count += len(results)
            total = result.get("total")
            if results and not (isinstance(total, int) and count >= total):
                next_target = (base_path, {**params, "page_number": result["current_page"] + 1})
        # else: bare array or unrecognized shape -> single page.

        if next_target is None:
            break
        if len(pages) >= _MAX_PAGES:
            # There's still a next page but we've hit the cap: fail loudly rather
            # than silently returning a truncated result with exit code 0.
            raise click.ClickException(
                f"--paginate stopped after {_MAX_PAGES} pages; "
                "possible pagination loop or an unexpectedly large result set"
            )
        base_path, params = next_target
    return _merge_pages(pages)


def _split_query(path: str, query_params: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Split any ``?query`` off ``path`` and merge it with ``query_params``.

    Pagination needs the query as a mutable dict so it can advance the cursor or
    page number while preserving the caller's other filters.
    """
    base = path
    params: Dict[str, Any] = {}
    if "?" in path:
        base, query = path.split("?", 1)
        params.update(parse_qsl(query))
    if query_params:
        params.update(query_params)
    return base, params


def _resolve_path(path: str, server_url: Optional[str]) -> str:
    """Normalize the PATH argument to something the client can request.

    A relative path keeps its existing behavior (leading slash stripped; the
    client adds ``/__api__``). A full URL -- handy for pasting a ``paging.next``
    link -- is reduced to its API-relative path. Because the client is bound to
    a single server, a URL for a different host is rejected rather than silently
    sent to the configured server.
    """
    if not path.startswith(("http://", "https://")):
        return path.lstrip("/")  # client prepends /__api__ itself
    parsed = urlparse(path)
    server = urlparse(server_url or "")
    if server.hostname and not _same_host(parsed, server):
        raise click.ClickException(
            f"URL host '{parsed.netloc}' does not match the target server "
            f"'{server.netloc}'; 'posit connect api' only talks to the configured server."
        )
    return _next_page_path(path)


def _same_host(a: Any, b: Any) -> bool:
    """Whether two parsed URLs point at the same host:port.

    Compares hostnames case-insensitively and effective ports (filling in the
    scheme default), so e.g. ``c.example`` and ``C.EXAMPLE:443`` over https match.
    """
    if (a.hostname or "").lower() != (b.hostname or "").lower():
        return False
    return _effective_port(a) == _effective_port(b)


def _effective_port(parsed: Any) -> Optional[int]:
    """The URL's port, defaulting by scheme. Malformed ports become a CLI error.

    ``urlparse(...).port`` raises ``ValueError`` on a non-numeric port (e.g.
    ``:abc``); surface that as a clean error rather than a traceback.
    """
    defaults = {"http": 80, "https": 443}
    try:
        return parsed.port or defaults.get(parsed.scheme)
    except ValueError as exc:
        raise click.ClickException(f"invalid port in URL: {exc}") from exc


def _next_page_path(next_url: str) -> str:
    """Turn an absolute ``paging.next`` URL into a path the client can request.

    The client prepends ``/__api__``, so strip everything up to and including
    that marker and keep the remainder (with any query string).
    """
    parsed = urlparse(next_url)
    marker = "/__api__/"
    idx = parsed.path.find(marker)
    rel = parsed.path[idx + len(marker) :] if idx != -1 else parsed.path.lstrip("/")
    return f"{rel}?{parsed.query}" if parsed.query else rel


def _merge_pages(pages: List[Any]) -> Any:
    """Combine paginated pages into a single result.

    A single page is returned unchanged (so unpaged endpoints behave exactly as
    without ``--paginate``). Connect's paged endpoints wrap rows in a ``results``
    array; across multiple pages those arrays are concatenated. If any page
    lacks a ``results`` list, the raw pages are returned rather than dropping
    data silently.
    """
    if len(pages) == 1:
        return pages[0]
    merged: List[Any] = []
    for page in pages:
        rows = page.get("results") if isinstance(page, dict) else None
        if not isinstance(rows, list):
            return pages
        merged.extend(rows)
    return merged


def _header_lines(result: Any, status: int) -> "list[str]":
    """Yield the HTTP status line and response header lines, gh/curl-style."""
    raw = getattr(result, "_response", None)
    version = getattr(raw, "version", 11) if raw is not None else 11
    reason = getattr(result, "reason", "") or ""
    lines = [f"HTTP/{version // 10}.{version % 10} {status} {reason}".rstrip()]
    if raw is not None:
        lines.extend(f"{name}: {value}" for name, value in raw.getheaders())
    return lines


def _render_success(value: Any, jq_program: Any = None) -> Optional[str]:
    """Render a successful response body, optionally filtered through jq.

    Returns the text to print, or None for an empty body (e.g. 204). Mirrors
    ``gh api``: with a jq filter, each result is on its own line -- strings raw
    (unquoted), everything else compact JSON; without a filter, pretty-printed.

    This *renders* rather than prints so the caller can emit headers and body
    together only after rendering succeeds: a jq runtime failure must abort
    before any output, not leak partial output (e.g. headers) to stdout.
    """
    if value in (None, ""):
        return None
    if jq_program is None:
        return _dumps(value)
    # A filter can compile cleanly yet fail at runtime (e.g. error(...) or a
    # type mismatch against the actual payload). .all() materializes every
    # result first, so a failure raises here before anything is printed --
    # surface it as a clean CLI error, not a traceback.
    try:
        results = jq_program.input_value(value).all()
    except ValueError as exc:
        raise click.ClickException(f"jq: {exc}") from exc
    if not results:
        # Zero matches -> no body (a blank line would falsely signal output).
        # This is distinct from a single empty-string result, which prints "".
        return None
    return "\n".join(item if isinstance(item, str) else json.dumps(item) for item in results)


def _dumps(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return str(value)
