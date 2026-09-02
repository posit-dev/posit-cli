# posit-cli

A friendly command-line interface for Posit products, in the spirit of [`gh`](https://cli.github.com/).

```console
$ posit connect login https://connect.example.com             # OAuth, tokens in your OS keyring
$ posit connect api v1/user -q .username                      # gh-api-style raw request
$ posit connect publish . --server https://connect.example.com
$ posit connect publish . --init                              # configure without publishing
```

This project is in early-stage development and so far only supports Posit Connect's APIs.

## Installation

`posit-cli` requires Python 3.9 or newer.

Install [`posit-cli` from PyPI](https://pypi.org/project/posit-cli/) with
[`uv`](https://docs.astral.sh/uv/):

```console
uv tool install posit-cli
```

To get unreleased changes, install from GitHub instead:

```console
uv tool install git+https://github.com/posit-dev/posit-cli.git
```

If you authenticate to GitHub over SSH, use the `git+ssh://` form (uv requires
the `git@` username):

```console
uv tool install git+ssh://git@github.com/posit-dev/posit-cli.git
```

Each of these puts the `posit` executable on your `PATH`. To upgrade later, run
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

**3. Publish.** Run the command from your project directory:

```console
$ cd my-app
$ posit connect publish . --server https://connect.example.com
```

If the project has not been configured yet, an interactive terminal opens the
setup wizard before continuing with the publish. The generated
`.posit/publish` configuration is reused on later runs.

The server is needed only for the first publish. Later publishes reuse the
saved deployment record:

```console
$ posit connect publish .
```

Anything `rsconnect` can deploy remains available under `posit connect deploy`.
Explore `posit connect --help` for the full command set.

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

## `posit connect publish`

`posit connect publish` is the main workflow. On a fresh project it opens a
Questionary-powered setup wizard in an interactive terminal and then publishes
the content:

```console
$ posit connect publish . --server https://connect.example.com
```

Use `--init` when you want to configure the project without publishing it:

```console
$ posit connect publish . --init
$ posit connect publish . --init --type python-fastapi --entrypoint app.py --title "Sales API"
```

Fresh projects do not prompt when stdin is non-interactive. Automation should
run `publish --init` with `--type` and `--entrypoint` first; Quarto content also
requires `--quarto-version`.

Configured projects can publish to a URL or saved server name:

```console
$ posit connect publish . --server https://connect.example.com
$ posit connect publish . --name production
$ posit connect publish . --config sales-api
$ posit connect publish . --deployment production
```

`--config` selects an exact `.posit/publish` configuration and `--deployment`
selects an exact deployment record. Successful publishes print the content URL
to stdout.

## `posit connect *`

`posit` wraps [`rsconnect-python`](https://github.com/posit-dev/rsconnect-python):
it re-exposes the full `rsconnect` command set under `posit connect`, in addition to the `api` utility.

## Using `posit` with Claude Code

This repo ships a skill (at [`skills/posit-cli/`](skills/posit-cli/)) that teaches
coding agents to drive `posit` — auth, `posit connect api`, and deploys. Install
it with the [`skills`](https://www.skills.sh/) CLI:

```console
npx skills add posit-dev/posit-cli
```
