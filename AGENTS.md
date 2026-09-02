# Repository Instructions

## Local Connect integration tests

The live integration suite requires Docker and a valid Posit Connect license copied to
`.connect-license.lic` at the repository root. This file is intentionally gitignored and must
never be committed.

For Posit developers with a local Connect checkout, copy the standard test license:

```bash
cp /path/to/connect/test/licenses/legacy-enterprise.lic \
  .connect-license.lic
```

Run the suite with:

```bash
just integration
```

This uses `posit-dev/with-connect` to start a temporary Connect container, provides
`CONNECT_SERVER` and `CONNECT_API_KEY` to pytest, and stops the container afterward.
