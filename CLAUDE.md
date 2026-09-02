# posit-cli

@AGENTS.md

A single, friendly CLI — `posit` — for working with Posit Connect, in the spirit of
[`gh`](https://cli.github.com/). Distribution name `posit-cli`, import package `posit_cli`,
executable `posit`.

- `posit connect api <path>` is a `gh api`-style raw REST client (OAuth-authenticated).
- Other `posit connect` commands (`login`, `deploy`, `add`, `list`, ...) are mounted dynamically
  from rsconnect-python's Click group, so they come for free and track upstream.

See `architecture-rsconnect-not-posit-sdk` in memory for why we wrap rsconnect-python (not
posit-sdk) and the OAuth-release gotcha.

## Design principles

- **Idiomatic first; deviate from rsconnect-python when it helps.** We deliberately built a
  separate project (not a patch to rsconnect) so we can make breaking changes freely. The CLI
  surface is *ours*. When rsconnect-python's naming or behavior is awkward, prefer what
  mainstream CLIs (especially `gh`, plus `curl`/`kubectl`) do, and what reads clearly to both
  humans and coding agents. Don't stay coupled to rsconnect's details for their own sake.
  - Example: rsconnect exposes `--insecure`/`-i` to skip TLS verification. We renamed it to
    `--no-tls-verify` (more explicit; "insecure" is vague) and freed the `-i` short flag so it
    can later mean `--include` as it does in `gh api`.
- **`posit connect api` tracks `gh api` conventions** where they make sense for Connect. Where a
  `gh` idiom doesn't fit Connect (e.g. `{owner}/{repo}` path placeholders, GraphQL), drop it
  rather than fake it.
- **Mounted rsconnect commands stay as-is** unless we have a specific reason to override one —
  the value of mounting is that they track upstream. Overriding a name means owning it.

## Conventions

- Keep credential flags consistent with the mounted rsconnect commands where they overlap
  (`-n/--name`, `-s/--server`, `-k/--api-key`, env `CONNECT_SERVER`/`CONNECT_API_KEY`/
  `CONNECT_INSECURE`) so the whole `posit connect` surface feels uniform — even when we rename
  the flag, keep honoring the shared env var.
- `posit connect api` uses rsconnect's *internal* client (`RSConnectExecutor` ->
  `RSConnectClient`), which has no stability contract. `tests/test_rsconnect_contract.py` guards
  the surface we depend on; pin the rsconnect version and re-verify on bumps.

- The git tag sets the version, through `hatch-vcs`. `pyproject.toml` has no `version` field.
  Do not add one.

See `RELEASE.md` for how to cut a release to PyPI.
