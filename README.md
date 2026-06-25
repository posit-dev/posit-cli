# posit-cli

A friendly command-line interface for Posit products, in the spirit of [`gh`](https://cli.github.com/).

```console
$ posit connect login https://connect.example.com             # OAuth, tokens in your OS keyring
$ posit connect api v1/user -q .username                      # gh-api-style raw request
$ posit connect deploy streamlit ./my-app                     # everything rsconnect can do
```

## Installation

`posit-cli` isn't on PyPI yet. Install the latest version straight from GitHub
with [`uv`](https://docs.astral.sh/uv/):

```console
uv tool install git+https://github.com/posit-dev/posit-cli.git
```

If you authenticate to GitHub over SSH, use the `git+ssh://` form instead (uv
requires the `git@` username):

```console
uv tool install git+ssh://git@github.com/posit-dev/posit-cli.git
```

Either way this puts the `posit` executable on your `PATH`. To upgrade later, run
`uv tool upgrade posit-cli`. See uv's
[Git authentication docs](https://docs.astral.sh/uv/concepts/authentication/git/)
for tokens and other hosts.

## Getting started

**1. Log in.** Point `posit` at your Connect server and authenticate. This runs
an OAuth 2.1 flow in your browser and saves the tokens in your OS keyring, so
you only do it once per server:

```console
$ posit connect login https://connect.example.com
```

**2. Try a request.** Confirm you're connected by asking Connect who you are:

```console
$ posit connect api v1/user -q .username
```

**3. Deploy something.** Anything `rsconnect` can deploy, `posit` can too:

```console
$ posit connect deploy streamlit ./my-app
```

That's it — from here, explore `posit connect --help` for the full command set.

## Authentication

`posit connect login` runs an OAuth 2.1 flow and stores tokens in your OS
keyring; `posit connect api` and the deploy commands reuse those credentials
automatically (including token refresh). You can also point at a server ad hoc
with `--server`/`CONNECT_SERVER` and `--api-key`/`CONNECT_API_KEY`.

## `posit connect api`

A `gh api`-style raw REST client, authenticated with your saved credentials.
`PATH` is relative to the Connect API root (the `/__api__` prefix is added for
you):

```console
$ posit connect api v1/user                          # GET, pretty-printed JSON
$ posit connect api v1/user -q .username             # filter with a jq expression
$ posit connect api "v1/content?limit=3" -q '.[].name'
```

`-q`/`--jq` runs the response through [jq](https://jqlang.github.io/jq/), like
`gh api --jq`: string results print unquoted, one per line.

`-i`/`--include` prepends the HTTP status line and response headers to the
output (handy for inspecting rate limits, request IDs, or the server version):

```console
$ posit connect api v1/user -i
```

`--paginate` (GET only) follows Connect's pagination and prints all pages'
results combined. It handles both of Connect's pagination styles — the
cursor style (e.g. `v1/audit_logs`) and the page-number style (e.g.
`v1/users`, `v1/groups`) — and leaves unpaginated endpoints unchanged:

```console
$ posit connect api v1/users --paginate -q 'length'   # count every user
```

`PATH` may also be a full URL on the configured server — convenient for pasting
a `paging.next` link straight back in. A URL for a different host is rejected.

### Query parameters vs. request body

Like `gh api`, `-f`/`-F` fields default to a **POST request body** (adding any
field flips the method to POST unless you pass `-X`). To send **query
parameters** on a read, put them in the path or force `GET`:

```console
$ posit connect api "v1/users?page_size=5"   # query params in the path
$ posit connect api v1/users -X GET -f page_size=5          # or force GET
$ posit connect api v1/content -f name=my-app              # POST body (creates content)
```

## `posit connect *`

`posit` wraps [`rsconnect-python`](https://github.com/posit-dev/rsconnect-python):
it re-exposes the full `rsconnect` command set under `posit connect`, in addition to the `api` utility.

## Status

Early/experimental. Connect only for now but eager to add other products too!
