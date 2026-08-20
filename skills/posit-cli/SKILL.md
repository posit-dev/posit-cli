---
name: posit-cli
description: >-
  Use the `posit` CLI to work with Posit Connect — logging in, making raw
  authenticated calls to the Connect REST API (`posit connect api`, a
  gh-api-style client), executing Python and R programs (`posit connect run`), and
  deploying or managing content. Use this whenever the
  user mentions `posit`, posit-cli, Posit Connect, the Connect API, or deploying
  apps/notebooks/APIs to Connect (Streamlit, Shiny, FastAPI, Flask, Dash, Quarto,
  Bokeh, Gradio, Panel, Voila, etc.), or managing Connect content, users, groups,
  environments, or OAuth integrations — even when they don't name the exact
  command. The `posit` tool is new and not in your training data, so consult this
  skill instead of guessing flags or endpoints.
---

# Using the `posit` CLI

`posit` is a friendly CLI for Posit Connect, built in the spirit of GitHub's
[`gh`](https://cli.github.com/). Today everything lives under `posit connect`,
which has two halves:

- **`posit connect api <path>`** — a `gh api`-style raw REST client for the
  Connect API. This is your primary tool for anything that isn't a deploy: reading
  and writing content, users, groups, tags, environments, audit logs, etc.
- **`posit connect run <path>`** — execute one Python or R source file, or a
  directory containing a runnable source file, through a temporary Connect API.
  The compatibility implementation supports optional runtime selection, script
  arguments, and `--detach`.
- **The full `rsconnect` command set** (`login`, `deploy`, `content`, `system`,
  `add`, `list`, ...) is mounted under `posit connect`, so those come for free and
  track [rsconnect-python](https://github.com/posit-dev/rsconnect-python) upstream.

If the tool isn't installed, see "Installing the CLI" at the bottom.

## First: discover the live command surface

The mounted `rsconnect` commands track upstream and their flags can change, so the
help text is the source of truth — read it rather than guessing:

```console
posit connect --help              # all subcommands
posit connect <command> --help    # flags for one command
posit connect deploy --help       # the deploy subcommands (streamlit, shiny, ...)
```

`posit connect api --help` and the rest of this skill cover the `api` command,
while `posit connect run --help` is the source of truth for the compatibility
command.

## Authentication

Most commands need credentials for a Connect server. Three ways, in order of
preference:

1. **OAuth login (recommended).** Runs an OAuth 2.1 browser flow once per server
   and stores tokens in your OS keyring; `api` and the deploy commands reuse them
   automatically, refreshing on expiry:
   ```console
   posit connect login https://connect.example.com
   posit connect login https://connect.example.com --use-device-code   # headless
   ```
2. **Ad hoc flags / env vars.** Point at a server for a single command:
   ```console
   posit connect api v1/user -s https://connect.example.com -k "$CONNECT_API_KEY"
   export CONNECT_SERVER=https://connect.example.com
   export CONNECT_API_KEY=...        # honored by the whole `posit connect` surface
   ```
3. **Saved API-key nickname.** `posit connect add -n myserver -s ... -k ...` saves
   a credential you can later select with `-n/--name myserver`.

Shared credential flags across `posit connect` commands: `-n/--name` (saved
server), `-s/--server` (env `CONNECT_SERVER`), `-k/--api-key` (env
`CONNECT_API_KEY`), `--no-tls-verify` (env `CONNECT_INSECURE`; note: rsconnect
commands spell this `-i/--insecure`), `-c/--cacert <file>`.

## `posit connect run`

The initial compatibility client accepts one Python or R source file, or a
directory containing a runnable source file, and waits for its temporary API
invocation to finish:

```console
posit connect run examples/hello.py
posit connect run examples/hello
posit connect run examples/hello.py -- --name Ada
posit connect run examples/hello.py --runtime python3.12 --detach
posit connect run examples/hello.R --runtime r4.5
```

For directory inputs, `__main__.py`, `main.py`, `app.py`, `main.R`, and `app.R`
are recognized automatically. A directory with exactly one Python or R source
file may use any filename. Directory contents are included in the bundle.

It creates content with `POST /v1/content`, uploads either a zero-dependency
Python WSGI API bundle or a Python API bundle that runs R through `rpy2` with
its R runtime metadata to
`/v1/content/{guid}/bundles`, deploys it with
`POST /v1/content/{guid}/deploy`, invokes the content URL, prints the captured
output, and deletes the temporary content. `--detach` leaves the deployed
content in place and prints its URL. R programs are submitted as Python API
content using `rpy2`; the Connect administrator must enable
`[Python] Flag = rpy2-cffi-mode-auto`. Native batch jobs, resource overrides, and
artifact pulling are not implemented yet.

## `posit connect api` — the raw REST client

```console
posit connect api <PATH> [options]
```

`PATH` is **relative to the Connect API root**; the `/__api__` prefix is added for
you. So `v1/user`, `v1/content`, `"v1/content?limit=3"`. (A full URL is also
accepted — handy for pasting a `paging.next` link back in — as long as its host
matches the server this call targets; a URL for a different host is rejected so
you can't accidentally cross servers.)

By default it does a `GET` and pretty-prints the JSON response. Errors print to
stderr and exit non-zero.

### Method, fields, and the GET-vs-POST rule (important)

This mirrors `gh api` and trips people up, so internalize it:

- `-f/--raw-field key=value` adds a **string** field.
- `-F/--field key=value` adds a **typed** field: `true`/`false`/`null`, integers
  and floats are parsed as such; `@file` reads a file, `@-` reads stdin; anything
  else stays a string.
- **Adding any `-f`/`-F` field flips the method to `POST` and sends the fields as
  a JSON request body** — unless you pass `-X/--method` explicitly.

So to send **query parameters on a read**, do NOT reach for `-f` (that would POST
a body Connect rejects). Instead put them in the path, or force `GET`:

```console
posit connect api "v1/content?name=my-app&limit=5"     # query params in the path
posit connect api v1/content -X GET -f limit=5          # or force GET
posit connect api v1/content -f name=my-app             # POST body → CREATES content
```

Other request options:

- `-X/--method GET|POST|PUT|PATCH|DELETE` — set the method explicitly.
- `-H/--header "Key: value"` — add a request header (repeatable).
- `--input FILE` — send a raw request body from a file (`-` for stdin). Cannot be
  combined with `-f`/`-F`.

### Shaping output

- `-q/--jq EXPR` — filter the JSON response through a [jq](https://jqlang.github.io/jq/)
  expression, exactly like `gh api --jq`. String results print **unquoted**, one
  per line; everything else prints as compact JSON. The filter is compiled before
  the request, so a typo fails fast.
- `-i/--include` — prepend the HTTP status line and response headers (useful for
  the server version, request IDs, rate limits).
- `--paginate` — **GET only.** Follow Connect's pagination and print every page's
  results combined. It understands both Connect styles (cursor-based like
  `v1/audit_logs`, and page-number based like `v1/users`, `v1/groups`) and leaves
  non-paginated endpoints unchanged. Cannot be combined with `-i`.

### Recipes

```console
# Who am I?
posit connect api v1/user -q .username

# Server version (use -i on any call to also see it as a response header)
posit connect api server_settings -q .version

# List content, just names and GUIDs
posit connect api v1/content -q '.[] | "\(.guid)  \(.title)"'

# Find content by name
posit connect api "v1/content?name=my-app" -q '.[0].guid'

# Count every user across all pages
posit connect api v1/users --paginate -q '.[].username' | wc -l

# Inspect one content item
posit connect api v1/content/<guid>

# Create content (POST body — fields imply POST)
posit connect api v1/content -f name=my-app -f title="My App"

# Update fields with PATCH
posit connect api v1/content/<guid> -X PATCH -f title="New title"

# Delete
posit connect api v1/content/<guid> -X DELETE

# Send a complex JSON body from a file
posit connect api v1/content -X POST --input ./body.json
```

If an *implicit* POST (fields, no `-X`) fails with a 4xx, `api` adds a hint
reminding you that fields became a body and that query params belong in the path —
that's the GET-vs-POST rule above biting.

## Deploying content

Deploys go through the mounted `rsconnect` commands. Pick the subcommand that
matches the framework, point it at the project directory, and let it bundle and
push. Always check `--help` for the exact flags (they track upstream):

```console
posit connect deploy --help                     # list every framework
posit connect deploy streamlit ./my-app
posit connect deploy shiny ./my-shiny-app
posit connect deploy fastapi ./my-api
posit connect deploy quarto ./report
posit connect deploy manifest ./manifest.json   # deploy a prepared bundle
```

Available deploy targets include `api`, `bokeh`, `bundle`, `dash`, `fastapi`,
`flask`, `gradio`, `html`, `manifest`, `nodejs`, `notebook`, `panel`, `pyproject`,
`quarto`, `shiny`, `streamlit`, `tensorflow`, `voila`. Use `quickstart` to
scaffold a deployable project and `write-manifest` to produce a `manifest.json`.

## Other mounted commands

These are rsconnect commands — run `posit connect <command> --help` for details:

- `content` — content API operations (search, build, etc.).
- `system` — system/runtime API (caches, etc.).
- `integration` — manage OAuth integrations.
- `environment` — manage execution environments.
- `add` / `list` / `remove` / `details` / `info` — manage saved servers and
  deployment metadata.
- `login` / `logout` — OAuth credential management.
- `bootstrap` — create an initial admin user on a fresh Connect instance.

## When something fails

- Each `posit connect api` call targets **one** server — your default, or the one
  you pick with `-n/--name <nickname>` (or `-s/--server`). A full-URL `PATH` must
  match that server's host, or it's rejected on purpose (so you don't cross
  servers). Register more servers with `posit connect login`/`add`.
- A 4xx on an implicit POST usually means you used `-f`/`-F` to try to filter a
  read — move those params into the path or add `-X GET`.
- Auth errors: confirm the target with `posit connect list` / `--help`, re-run
  `posit connect login`, or pass `-s`/`-k` (or set `CONNECT_SERVER`/`CONNECT_API_KEY`).
- For self-signed TLS, use `--no-tls-verify` (or `-c/--cacert <file>`); set
  `CONNECT_INSECURE` to apply it everywhere.

## Installing the CLI

Install from PyPI with [`uv`](https://docs.astral.sh/uv/):

```console
uv tool install posit-cli    # `posit` onto your PATH
uv tool upgrade posit-cli    # later, to update
```

For unreleased changes, install from GitHub instead:

```console
uv tool install git+https://github.com/posit-dev/posit-cli.git
```

If GitHub is set up for SSH auth, use the `git+ssh://` form (uv requires the
`git@` username):

```console
uv tool install git+ssh://git@github.com/posit-dev/posit-cli.git
```

For tokens or other hosts, see uv's
[Git authentication docs](https://docs.astral.sh/uv/concepts/authentication/git/).
