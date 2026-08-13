# Posit Connect integration tests

These tests exercise `posit connect publish --init` and `posit connect publish`
against a live Posit Connect instance. Local runs require:

- Docker
- A valid Posit Connect license at `.connect-license.lic` in the repository root

For Posit developers with a local Connect checkout:

```console
cp /path/to/connect/test/licenses/legacy-enterprise.lic \
  .connect-license.lic
```

Run them with:

```console
just integration
```

The command uses `posit-dev/with-connect` to provide a temporary Connect
instance and set `CONNECT_SERVER` and `CONNECT_API_KEY`. CI uses the same
utility through its GitHub Action.
