# ctmodbus instructions

## Project context

Read [docs/STATUS.md](docs/STATUS.md) for current work and validation gaps.
Read [docs/DECISIONS.md](docs/DECISIONS.md) headings and entries relevant to the
task; include D01–D08 and D11–D12 for cross-cutting architecture changes. Update
these files alongside meaningful changes using the global continuity guidance.

Use uv and the checked-in lockfile. Python 3.11 is the baseline; CI covers
Python 3.11–3.14 on Linux x86-64/ARM64, Windows, and macOS.
The 0.x compatibility waiver applies only to the migration (D01).

Until preparing the `1.0.0rc1` release, run ctmodbus and its tests with the
adjacent ctui checkout by adding `--with-editable ../ctui` to `uv run`. This is
a temporary development override: do not change the declared ctui dependency
or lockfile merely to use the checkout. Release validation must omit the
override and use the intended published PyPI version.

## Project constraints

ctmodbus is an asynchronous Modbus device-testing tool using ctui and PyModbus.
Preserve one application-owned connection, serialized device operations,
validated responses, explicit uncertain-write reporting, and project isolation.
Use native async device I/O; offload blocking discovery/certificate loading.
Pure parsing and formatting can remain synchronous.

Use `CtuiApp`, `@command`, and the same dispatch path for TUI and CLI. Use ctui
configs for profiles and records for decoded operations; never persist live
clients/tasks. Preserve the policies in the decision log when changing these
boundaries. Expansion beyond the agreed feature set requires an actual task.

## Commands and verification

```bash
uv sync --locked --python 3.11
uv run --with-editable ../ctui ctmodbus
uv run --python 3.11 --with-editable ../ctui python -m unittest discover -s tests -v
uv run --with-editable ../ctui black --check src tests
uv run --with-editable ../ctui isort --check-only src tests
uv run --with-editable ../ctui pylint src/ctmodbus
uv lock --check
git diff --check
uv build
```

Packaging/release changes also need isolated wheel/sdist smoke tests via
`tests/smoke_test.py`. Follow [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
POSIX PTYs cover serial framing; physical adapters still require manual checks.
TLS integration requires OpenSSL and otherwise skips. Record skipped checks.
Publishing requires release approval; pushing a version tag triggers publication.

## Code map

- `src/ctmodbus/app.py`: lifecycle, connection commands, profiles, project guards,
  records, progress, cancellation, and shutdown.
- `src/ctmodbus/connection.py`: settings, client factory, serialization, timeouts.
- `src/ctmodbus/operations.py`: typed reads/writes, chunking, response validation.
- `src/ctmodbus/tags.py`: project tag storage, codecs, commands, and TOML exchange.
- `src/ctmodbus/discovery.py`: advisory serial/local-service discovery.
- `src/ctmodbus/formatting.py`: timestamps and safe result rendering.
- `src/ctmodbus/commands.py`: application entry point.
- `tests/`: unittest coverage, local server fixture, distribution smoke test.
- `.github/workflows/`: platform tests and tag-triggered publishing.
- [MIGRATION.md](MIGRATION.md), [CHANGELOG.md](CHANGELOG.md), and the release
  checklist describe migration guidance, user-facing changes, and release gates.
