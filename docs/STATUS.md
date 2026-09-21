# Project status

Last reconciled: 2026-09-21, `dev-v1.0.0` at `cf3fb59`, plus the uncommitted tag
import/export command rename. Working tree was clean at task start.

## Current state

- Async migration, TLS, project-scoped typed tags (`5eb04ee`), and USB identity
  in serial completion (`4718ddd`) are implemented. Architecture and accepted
  choices are in [DECISIONS.md](DECISIONS.md).
- Version remains `1.0.0rc1`; dependencies are `ctui==1.0.0rc1` and
  `pymodbus[serial]>=3.15.0,<3.16` (locked to 3.15.0), Python >=3.11,<4.
- During development, local commands and tests use the adjacent `../ctui`
  checkout through `uv run --with-editable ../ctui`. This temporary override
  leaves dependency metadata unchanged. Release validation must use the chosen
  published PyPI ctui version without the override.
- The owner reported RC1 unpublished on September 18. Remote refs, CI, and
  publication state have not been refreshed; CHANGELOG remains Unreleased.
- The September 21 audit updates global documentation ownership rules, expands
  contracts throughout all 16 project Python files, and reconciles all seven
  Markdown files. Global instructions need separate synchronization per machine.
- Tag lifecycle, concurrency, and partial-output discrepancies are recorded in
  [D12](DECISIONS.md#d12--implementation-discrepancies-and-ctui-proposals).
  This documentation audit does not resolve those runtime issues.
- Tag TOML commands are grouped with the other tag-management commands as
  `tag export` and `tag import`; the unreleased `export tags` and `import tags`
  spellings are not retained as aliases. Both path arguments use the shared
  ctui path completer from the adjacent development checkout.

## Next steps and validation gaps

1. Review and address D12's tag-read partial output/serialization and tag-import
   confirmation/transaction/project isolation gaps with focused regressions.
   ctui enhancements listed there remain proposals, not dependency commitments.
2. Exercise tag completion, collision confirmation, and typed output in a real
   terminal; verify USB metadata on physical serial ports.
3. Before `1.0.0rc1` release validation, select the published PyPI ctui version,
   update the dependency and lockfile if needed, and stop using the local
   editable override. Then run the [release checklist](../RELEASE_CHECKLIST.md)
   on the intended release revision, including the full platform matrix,
   artifacts, terminal checks, and physical RTU/ASCII devices. Record actual
   evidence here.
4. Obtain release approval before publication. Before stable 1.0, adopt tested
   stable ctui and repeat release gates (D08).

Polling, device cloning/simulation, proxies, raw/fuzzy requests, tunneling, and
historian integration remain deferred. No implementation blocker is established;
release readiness lacks final-revision and manual/remote validation.

## Validation evidence

- Historical September 13 migration through `7914437`: 34 tests reported passing
  on Python 3.11 and 3.14, local TCP/UDP and PTY serial, quality/lock checks,
  wheel/sdist builds, and isolated installed-artifact smoke checks.
- Historical TLS/workflow follow-up through `426048a`: prior session reported
  45 passing tests, quality/lock/build/workflow checks, and both artifact smoke
  tests. These supersede the initial test count, not the manual/remote gates.
- September 20 tag work based on `4e34098`: full suite reported 53 passing tests
  on Python 3.11 and passing quality/build/artifact checks before final follow-ups.
  Later singular syntax/read-all/signed-value updates had 10 focused tag tests.
  Do not treat the earlier full-suite/artifact checks as tests of final `5eb04ee`.
- September 20 serial completion based on `5eb04ee`, committed at `4718ddd`:
  30 discovery/command tests and formatting/import/lint/whitespace checks passed.
- September 21 documentation audit on `4718ddd`: Python syntax and docstring
  coverage checked; non-docstring ASTs match HEAD in all 16 Python files.
  Black, isort, pylint (10.00/10), and whitespace checks passed.
  All 40 focused command/tag/discovery tests passed; local Markdown links and
  anchors checked. Full transport/matrix and artifact checks were not rerun for
  this documentation-only change.
- September 21 tag command rename and shared path-completer integration on
  `cf3fb59`: all 11 focused tag tests passed on Python 3.11 using the adjacent
  editable ctui checkout.

## Audit source coverage

Reviewed the three locally available ctmodbus Codex session files (including
overlapping replayed history), current source/tests, all seven project Markdown
files, and relevant Git history. Earlier September 13/18 evidence is retained
from Git-tracked notes rather than claimed as newly rerun validation. Histories
only on other machines or unavailable account sessions were not accessible.
No additional project Markdown stash was found in the repository beyond those files;
private transcripts and machine-specific logs are not copied into this repository.
