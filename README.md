# posit-cli

A single, friendly command-line interface for [Posit Connect](https://posit.co/products/enterprise/connect/),
in the spirit of [`gh`](https://cli.github.com/).

`posit` wraps [`rsconnect-python`](https://github.com/posit-dev/rsconnect-python):
it re-exposes the full `rsconnect` command set under `posit connect` and adds a
`gh api`-style raw REST command.

```console
$ posit connect login --server https://connect.example.com   # OAuth, tokens in your OS keyring
$ posit connect api v1/user                                   # gh-api-style raw request
$ posit connect deploy streamlit ./my-app                     # everything rsconnect can do
```

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

## Installation

```console
uv tool install posit-cli
```

## Authentication

`posit connect login` runs an OAuth 2.1 flow and stores tokens in your OS
keyring; `posit connect api` and the deploy commands reuse those credentials
automatically (including token refresh). You can also point at a server ad hoc
with `--server`/`CONNECT_SERVER` and `--api-key`/`CONNECT_API_KEY`.

> `posit connect add` stores a **plaintext API key** in `servers.json`. Prefer
> `posit connect login` where possible.

## Status

Early/experimental. Connect only for now; Workbench support is deferred.
