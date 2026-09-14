# Release checklist

Target release tag: `v1.0.0rc1`. Python package version: `1.0.0rc1`.

## Automated gates

- [ ] `uv lock --check`
- [ ] `uv run black --check src tests`
- [ ] `uv run isort --check-only src tests`
- [ ] `uv run pylint src/ctmodbus`
- [ ] `uv run python -m unittest discover -s tests -v`
- [ ] CI green on Linux, macOS, and Windows with Python 3.11–3.14.
- [ ] Build wheel and sdist with `uv build`.
- [ ] Smoke-test each distribution in an isolated environment:
  `uv run --isolated --no-project --with dist/ARTIFACT tests/smoke_test.py`.

## Manual release checks

- [ ] Run the TUI in a real terminal; check completion, output scrolling, progress,
  error display, cancellation during slow I/O, and exit cleanup.
- [ ] Test RTU and ASCII against physical serial adapters/devices. Automated PTY
  checks verify framing but do not reproduce RS-485 timing or driver behavior.
- [ ] Review README commands and changelog against the intended release.
- [ ] Before final 1.0.0: adopt the published stable ctui 1.0 release, regenerate
  the lockfile, update ctmodbus version and changelog, and rerun all gates.
- [ ] Publish only after release approval; creating/pushing a version tag triggers
  the existing trusted-PyPI publishing workflow.

## Local migration validation

The migration is kept at 1.0.0rc1. Local results are recorded in MIGRATION.md.
Cross-platform CI and physical-device checks remain release gates even when the
local suite passes. This migration does not publish packages or push tags.
