# Project status

Last reconciled: 2026-09-20, `dev-v1.0.0` at `4e34098`, plus the uncommitted tag
feature described below. Working tree was clean at task start.

## Current state

- The six migration milestones, TLS, and CI alignment are implemented through
  `426048a`; `d0e45e5` added project instructions and continuity notes.
- Package version is `1.0.0rc1`; `ctui==1.0.0rc1` and
  `pymodbus[serial]>=3.15.0,<3.16` (locked to 3.15.0); Python >=3.11,<4.
- Project-scoped typed tags are implemented with persistence, tagged reads and
  writes, endian-aware integer/float codecs, and atomic TOML exchange (D11).
- The owner confirmed on September 18 that RC1 was unpublished. No local
  `v1.0.0rc1` tag exists; changelog remains Unreleased. Remote refs, PRs,
  publication state, and CI results were not refreshed for this review.
- The global/project instruction split is committed at `4e34098`. Global
  instructions are machine-local and must be synchronized separately.

## Next steps and validation gaps

1. Reconcile remote changes before integration or release work. Exercise tag
   completion, collision confirmation, and typed output in a real terminal.
2. After feature work, follow [RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) on
   the intended release revision: source/lockfile checks, wheel/sdist smoke
   tests, metadata review, and verified remote CI across all 16 combinations.
3. Record real-terminal checks (completion, scrolling, progress/errors,
   cancellation, exit cleanup) and RTU/ASCII checks on physical adapters/devices,
   including revision, OS, Python, hardware, and outcomes. PTYs do not replace
   physical checks. No subsequent manual validation has been reported.
4. Obtain release approval and complete publisher/changelog prerequisites before
   tagging; verify publication using the release checklist. Before stable 1.0,
   adopt tested stable ctui 1.0 and repeat release gates (D08).

No implementation blocker is established. Release readiness lacks verified
remote results and recorded manual hardware/terminal checks.

## Deferred scope

Polling, device cloning/simulation, proxies, raw/fuzzy requests, tunneling,
and historian integration remain deferred. TLS is complete. ctui's optional job
manager, typing-marker ideas, and release plans are not ctmodbus commitments.

## Validation evidence

- Historical, September 13 through `426048a`: the prior local session reported
  45 passing tests, quality/lock/build checks, workflow checks, and isolated
  wheel/sdist smoke tests. This supersedes the initial 34-test migration result
  in [MIGRATION.md](../MIGRATION.md); it does not establish remote CI or hardware
  success. Original evidence review is preserved in `d0e45e5`.
- September 18 at `d0e45e5`: documentation content, local links, and whitespace
  reviewed; runtime tests not rerun.
- September 20 documentation edits on `d0e45e5`: content and local Markdown
  links reviewed; `git diff --check` passed. Runtime tests not run because no
  runtime or packaging behavior changed.
- September 20 tag implementation on `4e34098`: 53 tests passed on Python 3.11,
  including TCP/UDP, PTY serial, TLS, tag codecs/storage/I/O/import/export, and
  project isolation. Black, isort, pylint, lock, and whitespace checks passed;
  wheel and sdist builds and isolated installed-artifact smoke tests passed.
  Remote CI and manual terminal/hardware checks remain outstanding.
