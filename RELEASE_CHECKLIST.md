# Release checklist

Target release tag: `v1.0.0`. Python package version: `1.0.0`.
Merge the release-preparation PR from `dev-v1.0.0` into `main` before tagging.
Record each check's revision in [docs/STATUS.md](docs/STATUS.md); repeat release
gates on the intended `main` release revision after merging.

## Automated gates

Run every gate with published `ctui==1.0.0`, without the former
`--with-editable ../ctui` override. Confirm package metadata and the lockfile
both report ctmodbus `1.0.0` before starting.

- [ ] `uv sync --locked --python 3.11`
- [ ] `uv lock --check`
- [ ] `uv run --locked --python 3.11 black --check src tests`
- [ ] `uv run --locked --python 3.11 isort --check-only src tests`
- [ ] `uv run --locked --python 3.11 pylint src/ctmodbus`
- [ ] `uv run --locked --python 3.11 python -m unittest discover -s tests -v`
- [ ] `git diff --check`
- [ ] CI green on Linux x86-64, Linux ARM64, macOS, and Windows with Python 3.11–3.14.
- [ ] Build wheel and sdist with `uv build`.
- [ ] Smoke-test each distribution in an isolated environment:
  `uv run --python 3.11 --isolated --no-project --with dist/ARTIFACT tests/smoke_test.py`.

## Manual release checks

- [ ] Run the TUI in a real terminal; check completion, output scrolling, progress,
  error display, cancellation during slow I/O, and exit cleanup.
- [ ] Run the web UI; check completion, dialogs, sustained polling/request output,
  cancellation, and exit cleanup in a browser.
- [ ] Test RTU and ASCII against physical serial adapters/devices. Automated PTY
  checks verify framing but do not reproduce RS-485 timing or driver behavior.
- [ ] Review README commands and changelog against the intended release.
- [ ] Publish only after release approval; creating/pushing a version tag triggers
  the existing trusted-PyPI publishing workflow.

## Recording validation

Record dated results and their revision in [docs/STATUS.md](docs/STATUS.md).
Re-run these gates on the intended release revision; historical local results
do not establish cross-platform CI, physical-device behavior, or publication.

## GitHub and PyPI release setup

- [ ] Commit and push the release-preparation changes when authorized, then open
  a PR from `dev-v1.0.0` into `main` with the change summary and validation evidence.
- [ ] Review and merge the PR after required CI passes. Confirm `main` contains
  the intended 1.0.0 metadata, changelog and documentation, and validate that
  final revision before tagging it.
- [ ] Confirm the `pypi` GitHub environment and PyPI trusted publisher reference
  this repository and `.github/workflows/publish.yml`.
- [ ] Confirm the changelog has `## [1.0.0] - 2026-10-24`; update the date if the
  approved publication date changes. Missing version sections fail before
  publication.
- [ ] Review the diff against the previous release and start with a clean checkout.
- [ ] Inspect the wheel and sdist metadata, README, license, and dependencies.
- [ ] After release approval, create and push the annotated tag on the validated
  `main` release revision:

  ```bash
  git tag -a v1.0.0 -m "ctmodbus 1.0.0"
  git push origin v1.0.0
  ```

- [ ] Watch metadata validation, all 16 OS/Python verification combinations,
  quality checks, artifact smoke tests, attestation, and publication complete.
- [ ] Confirm the GitHub release includes curated changelog notes, generated
  notes, and distribution files; `v1.0.0` must be stable and marked latest.
- [ ] Confirm both distributions and attestations appear on PyPI, then install
  `ctmodbus==1.0.0` in a new environment and check help and a device workflow.
- [ ] Remove README's temporary checkout-installation note after publication.
- [ ] Never reuse an already published version; fix and increment it instead.
