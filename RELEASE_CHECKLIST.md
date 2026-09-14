# Release checklist

Target release tag: `v1.0.0rc1`. Python package version: `1.0.0rc1`.

## Automated gates

- [ ] `uv lock --check`
- [ ] `uv run black --check src tests`
- [ ] `uv run isort --check-only src tests`
- [ ] `uv run pylint src/ctmodbus`
- [ ] `uv run python -m unittest discover -s tests -v`
- [ ] CI green on Linux x86-64, Linux ARM64, macOS, and Windows with Python 3.11–3.14.
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

## GitHub and PyPI release setup

- [ ] Confirm the `pypi` GitHub environment and PyPI trusted publisher reference
  this repository and `.github/workflows/publish.yml`.
- [ ] Confirm the changelog has a `## [1.0.0rc1]` section and set its release date.
  Release notes select the exact version first, falling back to the base version
  for prereleases. Missing sections fail before publication.
- [ ] Review the diff against the previous release and start with a clean checkout.
- [ ] Inspect the wheel and sdist metadata, README, license, and dependencies.
- [ ] After release approval, create and push the matching annotated tag:

  ```bash
  git tag -a v1.0.0rc1 -m "ctmodbus 1.0.0rc1"
  git push origin v1.0.0rc1
  ```

- [ ] Watch metadata validation, all 16 OS/Python verification combinations,
  quality checks, artifact smoke tests, attestation, and publication complete.
- [ ] Confirm the GitHub release includes curated changelog notes, generated
  notes, and distribution files; `v1.0.0rc1` must be a prerelease, not latest.
- [ ] Confirm both distributions and attestations appear on PyPI, then install
  `ctmodbus==1.0.0rc1` in a new environment and check help and a device workflow.
- [ ] Never reuse an already published version; fix and increment it instead.
