# Repository instructions

## Project continuity

- Before working, read [docs/STATUS.md](docs/STATUS.md) and
  [docs/DECISIONS.md](docs/DECISIONS.md), then inspect the current branch,
  working tree, and recent commits. Reconcile stale notes with the code and
  the user's latest instructions.
- After meaningful work, update status with completed changes, checks actually
  run, remaining tasks, blockers, and concrete next steps. Include memory
  updates with the corresponding code changes.
- Record significant accepted decisions and rationale in the decision log.
  Label proposals, inferred rationale, and superseded decisions explicitly;
  do not turn assistant suggestions into user commitments.
- Keep status concise and use Git history for detailed changes. Link existing
  documentation rather than duplicating it. Use repository-relative paths;
  do not commit private transcripts, credentials, or machine-specific logs.
- Date validation evidence and identify its revision. Never infer publication
  or remote CI success from local tests or historical session summaries.
- Before a laptop handoff, record unfinished work and remaining validation.
  Code and notes must be committed and pushed to transfer through Git; pull
  the same branch on the receiving laptop before starting a new session.
  These files carry context, not automatic chat-history synchronization.

## Development preferences

- Use Conventional Commits: a suitable prefix such as `feat:`, `fix:`,
  `docs:`, `build:`, `test:`, or `ci:` and a concise description.
- Follow applicable official Python standards and PEPs, including packaging
  and versioning. Prefer official Python and PyPA documentation as references.
- Follow GitHub-recommended and sound development practices proportionately:
  clear commits and reviews, appropriate tests and CI, maintainable code,
  secure defaults, managed dependencies, and documented release procedures.
- Keep Python code and examples simple and approachable. Prefer typed public
  framework APIs and shared implementations over duplicated command paths.
- Use uv and the checked-in lockfile. Python 3.11 is the baseline; CI defines
  Python 3.11–3.14 on Linux x86-64/ARM64, Windows, and macOS.
- Update README examples when public behavior changes. The deliberate 0.x
  compatibility break is migration scope, not blanket permission for future
  undocumented breaking changes.

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
uv run ctmodbus
uv run --python 3.11 python -m unittest discover -s tests -v
uv run black --check src tests
uv run isort --check-only src tests
uv run pylint src/ctmodbus
uv lock --check
git diff --check
uv build
```

Run checks appropriate to the change. Documentation-only work ordinarily needs
content, link, and whitespace review. Runtime changes need relevant regression
tests; packaging/release changes also need isolated wheel/sdist smoke tests via
`tests/smoke_test.py`. Follow [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
POSIX PTYs cover serial framing; physical adapters still require manual checks.
TLS integration requires OpenSSL and otherwise skips. Record skipped checks.
Publishing requires release approval; pushing a version tag triggers publication.

## Code map

- `src/ctmodbus/app.py`: lifecycle, connection commands, profiles, project guards,
  records, progress, cancellation, and shutdown.
- `src/ctmodbus/connection.py`: settings, client factory, serialization, timeouts.
- `src/ctmodbus/operations.py`: typed reads/writes, chunking, response validation.
- `src/ctmodbus/discovery.py`: advisory serial/local-service discovery.
- `src/ctmodbus/formatting.py`: timestamps and safe result rendering.
- `src/ctmodbus/commands.py`: application entry point.
- `tests/`: unittest coverage, local server fixture, distribution smoke test.
- `.github/workflows/`: platform tests and tag-triggered publishing.
- [MIGRATION.md](MIGRATION.md), [CHANGELOG.md](CHANGELOG.md), and the release
  checklist describe migration scope, user-facing changes, and release gates.

Preferences were adapted from the owner's
[ctui instructions](https://github.com/ControlThings-io/ctui/blob/main/AGENTS.md)
and its status/decision files on 2026-09-18, plus direct ctmodbus instructions.
