# Test landscape: posit-cli

Investigation date: 2026-07-31. Scope: `tests/` against `src/posit_cli/`.

## Summary

| File | Purpose | Tests |
|---|---|---|
| `tests/test_api.py` | `posit connect api` argument handling, no network | 51 |
| `tests/test_cli.py` | Command-tree smoke tests | 4 (+8 parametrized) |
| `tests/test_rsconnect_contract.py` | Guards the rsconnect internal API surface | 2 |

Total: 65 test functions (64 collected test items after parametrization
counts as separate items; the exact number that runs is 64 per `pytest`).

Line coverage of `src/`: **96%** (251/261 statements). All uncovered lines
are in `src/posit_cli/connect/api.py`.

## How this was measured

```console
uv run --extra test python -m coverage run --source=src -m pytest tests
uv run --extra test python -m coverage report -m
```

No coverage tool or threshold is wired into `pyproject.toml` or CI today —
this was a one-off local run to find gaps, not a repeatable check.

## Gaps found

### 1. Uncovered lines in `api.py` (10 statements, 96% → could be 100%)

| Line(s) | Code | Why it's untested |
|---|---|---|
| 30 | `_read_at_value`: `return sys.stdin.read()` for `@-` | No test feeds a field or `--input` value via stdin. |
| 38 | `_parse_typed`: `@file` branch (`return _read_at_value(value)`) | No test exercises `-F key=@file` (typed field reading from a file). |
| 42 | `_parse_typed`: `false` branch | Only `true` is tested (`test_typed_field_parsing`); `false` is not. |
| 44 | `_parse_typed`: `null` branch | Not exercised at all. |
| 73 | `_split_headers`: malformed header (`raise click.BadParameter`, missing `:`) | The analogous field-parsing error (`test_bad_field_format`) is tested; the header one is not. |
| 238 | `api()`: `body = raw_body` when `--input` is used *without* conflicting fields | `test_input_conflicts_with_fields` only exercises the *rejection* path (`--input` + `-f` together); no test sends `--input` alone and checks it becomes the request body. |
| 283 | `api()`: `except RSConnectException as exc: raise click.ClickException(...)` | No test simulates `RSConnectExecutor`/`setup_client`/`request` raising `RSConnectException` (e.g. connection refused, unknown server). All error-path tests go through the `HTTPResponse` return value, not this exception path. |
| 458 | `_split_query`: `if query_params: params.update(query_params)` | Only reached when both a `?query` in `path` *and* a non-empty `query_params` dict collide during pagination; no test builds that combination directly (though pagination tests all pass `query_params=None` at the top level). |
| 535 | `_merge_pages`: `return pages` (unrecognized per-page shape, not falling back to `results`) | No test feeds `--paginate` a page missing a `results` list, to check pages are returned raw instead of silently dropped. |
| 584 | `_dumps`: `return str(value)` (non-dict/list scalar) | Every success/error test so far renders a dict, list, or empty body; no test renders a bare scalar (e.g. a plain string or number) through `_dumps`. |

None of these are exotic: each is a real, reachable branch a user can hit
(`-F count=@file`, `-F flag=false`, `--input body.json` alone, a Connect
server that's unreachable, a scalar JSON response). Recommend closing all
ten before calling coverage "done," since they're cheap unit tests, not new
infrastructure.

### 2. CLI-surface options with no dedicated test

Every `click.option` on `posit connect api` should have at least one test
that proves it's wired to the right effect. Checked against the option list
in `src/posit_cli/connect/api.py:84-173`:

| Option | Tested? |
|---|---|
| `PATH` argument | Yes |
| `--method`/`-X` | Yes |
| `--field`/`-F` | Yes |
| `--raw-field`/`-f` | Yes |
| `--header`/`-H` | Yes |
| `--input` | Partially — only the conflict-with-fields case (see gap #1, line 238) |
| `--jq`/`-q` | Yes |
| `--include`/`-i` | Yes |
| `--paginate` | Yes |
| `--name`/`-n` | Yes (via `test_credential_options_passed_to_executor`) |
| `--server`/`-s` | Yes (same test) |
| `--api-key`/`-k` | Yes (same test) |
| `--no-tls-verify` | Yes |
| `--cacert`/`-c` | **No test at all** |

`--cacert` is a real gap: it takes a `click.Path(exists=True, ...)`, so it
also needs a test that the path-existence validation itself works (a
missing file should be a clean Click error, not a traceback).

### 3. Environment-variable wiring is untested

`--server`, `--api-key`, `--no-tls-verify`, and `--cacert` all declare
`envvar=` (`CONNECT_SERVER`, `CONNECT_API_KEY`, `CONNECT_INSECURE`,
`CONNECT_CA_CERTIFICATE` respectively — see `CLAUDE.md`'s "Conventions"
section, which calls out keeping these consistent with rsconnect on
purpose). No test sets any of these env vars and checks the CLI picks them
up when the flag is omitted. This matters here specifically because
`CLAUDE.md` treats this env-var consistency as a project convention worth
guarding, similar to why `test_rsconnect_contract.py` exists — an accidental
rename would silently break scripts relying on the env var, not just the
flag.

### 4. `--version` is untested

`src/posit_cli/__main__.py` wires `@click.version_option(version=__version__)`
onto the top-level `cli` group. No test invokes `posit --version` and
checks it exits 0 and prints something. Cheap to add, and it's the one
thing `src/posit_cli/__init__.py`'s `importlib.metadata` fallback logic
(`__version__ = "0.0.0+unknown"` when not installed) has no test guarding
either — if that fallback ever throws instead of catching
`PackageNotFoundError`, nothing would catch it today.

### 5. Mounted rsconnect commands: presence-only, not behavior

`tests/test_cli.py` checks that expected rsconnect commands
(`add`, `deploy`, `list`, `details`, `remove`, `bootstrap`, `login`,
`logout`) are *present* in `connect.commands`, and that `deploy --help`
mentions `streamlit`. That's appropriate — deep-testing rsconnect's own
command behavior would duplicate rsconnect-python's own test suite, and
per `CLAUDE.md`'s design principle ("Mounted rsconnect commands stay as-is
... the value of mounting is that they track upstream"), that's
intentional, not a gap to close.

One real gap here: `EXPECTED_RSCONNECT_COMMANDS`'s comment
(`tests/test_cli.py:26-28`) is stale. It says:

> `login`/`logout` (OAuth) come from the rsconnect main-branch build we
> currently track; they should remain present once that work is released.

This described the *pre-pin* state. `rsconnect-python` is now pinned to the
released `>=1.30,<2` (this session's earlier change), where `login`/`logout`
already ship. The comment should be updated or removed — it now describes
a state that no longer exists, and a future reader would wrongly conclude
the dependency is still tracking `main`.

### 6. No integration test against a real Connect server

Everything in `test_api.py` mocks `RSConnectExecutor` — by design, this is
a fast, network-free unit-test suite (docstring: "no network"). posit-cli
has no equivalent — its only Connect-shaped guard is
`test_rsconnect_contract.py`'s introspection of rsconnect's internal API
surface, which checks shape, not live behavior.

Both reference projects keep integration tests structurally separate from
unit tests and run them against a real Connect server via
`posit-dev/with-connect` in CI:

- **rsconnect-python** interleaves integration tests into the *same*
  `tests/` tree as unit tests, gated by `pytest.skip()` helpers in
  `tests/utils.py` (`require_connect()`, `require_api_key()` — skip unless
  `CONNECT_SERVER`/`CONNECT_API_KEY` are set). `test_main_content.py` and
  `test_main_integration.py` register fake Connect endpoints with
  `httpretty` (`httpretty.register_uri(...)`) and drive them through the
  real `click` CLI (`CliRunner().invoke(cli, [...])`) — closer to full
  request/response round-trips than posit-cli's current
  mock-the-Python-object style.
- **posit-sdk-py** keeps a *separate* `integration/` tree entirely, driven
  by `integration/Makefile`'s `CONNECT_VERSIONS` matrix (a list of pinned
  Connect release versions run against a real server per version). Its
  *unit* tests (`tests/posit/connect/*.py`) mock HTTP directly with the
  `responses` library (`responses.get(url, json=..., match=[...])`) against
  real Connect JSON response fixtures loaded via `tests/posit/connect/api.py`'s
  `load_mock()` (reading from a `tests/posit/connect/__api__/` fixture
  tree) — a cleaner separation than either mocking the client object
  (posit-cli's current approach) or `httpretty` (rsconnect-python's).

Not flagging this as a must-fix: it's a meaningfully larger lift (Connect
license, `with-connect` action, matrix of Connect versions) than the unit
gaps above, and the project is early-stage. Worth deciding deliberately
rather than defaulting into it — and worth picking one of the two patterns
above rather than inventing a third.

### 7. No coverage enforcement

Nothing in `pyproject.toml` or `.github/workflows/ci.yaml` runs or
thresholds coverage. The 96% figure in this document is a one-off manual
measurement, not a number future changes are held to. Both reference
projects wire coverage into CI: posit-sdk-py enforces a hard floor via
`.coveragerc`'s `fail_under = 80` (plus `make cov`/`cov-xml` targets and an
`orgoro/coverage` PR-comment step); rsconnect-python produces
`coverage.xml` and posts it via the same `orgoro/coverage` action, without
a `fail_under` gate. If coverage matters to this project, it isn't
enforced anywhere yet — and posit-sdk-py's stricter, gated approach is the
better model given posit-cli is already at 96%.

## Priority if closing these

1. **Cheap, high-value, no new infra** — close the 10 uncovered lines
   (gap #1) and add `--cacert` + `--version` tests (gaps #2, #4). All unit
   tests, all mockable, no new dependencies.
2. **Cheap, correctness-adjacent** — fix the stale comment in
   `test_cli.py` (gap #5) and add env-var wiring tests (gap #3), since
   `CLAUDE.md` calls out env-var consistency as a deliberate convention.
3. **Bigger decisions, not urgent** — coverage enforcement in CI (gap #7)
   and a real integration-test job against Connect (gap #6). Worth a
   deliberate yes/no from you, not something to default into.
