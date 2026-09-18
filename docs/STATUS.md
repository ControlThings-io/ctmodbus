# Project status

Last reconciled: 2026-09-18, `dev-v1.0.0` at `426048a`.

## Evidence and scope

Reviewed the locally available ctmodbus conversation of September 13 (migration,
TLS, commit conventions, release target, and CI alignment), its overlapping
review log, this September 18 request, and Git history since August 22, 2026.
There are nine commits on the active branch in that period, all September 13;
seven additional commits on a backup ref preserve the pre-rewording history,
not seven additional milestones. Earlier baseline: `f8f91d9` on August 20.
The owner confirmed the August 22, 2026 cutoff and that no other plans or
decisions need preserving.

Also read the owner's GitHub ctui [instructions](https://github.com/ControlThings-io/ctui/blob/main/AGENTS.md),
[status](https://github.com/ControlThings-io/ctui/blob/main/docs/STATUS.md), and
[decisions](https://github.com/ControlThings-io/ctui/blob/main/docs/DECISIONS.md)
on September 18 for transferable preferences. Other-laptop/product chats absent
from local transcripts were unavailable; this is not a claim to have reviewed
all account-wide conversations. Private logs are not required to use these notes.

## Current state

- All six migration milestones are implemented, followed by TLS and CI alignment.
- Package version is `1.0.0rc1`; dependencies include `ctui==1.0.0rc1` and
  `pymodbus[serial]>=3.15.0,<3.16`, locked to 3.15.0. Python requires >=3.11,<4.
- Active branch and local `origin/dev-v1.0.0` both point to `426048a`; local
  `main`/`origin/main` remain at `f8f91d9`. Remote refs were not refreshed.
- The working tree was clean before adding these three memory files.
- No local `v1.0.0rc1` tag exists; the changelog still says Unreleased.
  The owner confirmed on September 18 that RC1 has not been published and
  feature work is still ongoing. No subsequent manual validation was reported.
  Remote PR/merge state and CI outcomes have not been verified in this review.
- ctui's own September 18 notes report its RC1 published and RC2 planned.
  That is dependency context, not evidence that ctmodbus was released or a
  decision to move ctmodbus to RC2.

## Completed milestones

All entries below were implemented September 13, 2026.

| Commit | Completed work |
| --- | --- |
| `c225522` | ctui 1.0 RC application foundation; Python 3.11 baseline; modern PyModbus; unified pyproject packaging; removed legacy setup/version files. |
| `39d0633` | Native async TCP/UDP/RTU/ASCII, discovery, one serialized connection, lifecycle cleanup. |
| `b5dabf8` | Typed range reads and multi-value writes, validation, acknowledgement checks, partial results, safe formatting. |
| `c6054e2` | Named profiles, project records/history, progress, cancellation, and project-switch guards. |
| `500949f` | Command/lifecycle regression tests, actual TCP/UDP and PTY serial tests, injected-terminal tests, modern server fixture. |
| `7914437` | Migration docs, README, changelog, release checklist, CI and isolated installed-package smoke tests. |
| `ac4af8d` | Async Modbus TLS, server verification, private CA/client certificates, explicit insecure mode, persisted settings, TLS integration tests. |
| `4fcc4f2` | Explicit release tag `v1.0.0rc1`. |
| `426048a` | ctui-aligned 16-combination CI, quality/build/artifact gates, version validation, attestations, curated notes and prerelease handling. |

## Next concrete steps

The owner is still developing features; release preparation is a later phase.
The remaining feature list has not yet been supplied. Use
[RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) as the
authoritative release procedure rather than marking historical checks complete.

1. Capture the owner's remaining feature work as concrete tasks, implement it,
   and record relevant validation. Reconcile remote changes with this branch.
2. On the intended release revision, rerun source/lockfile checks and isolated
   wheel/sdist smoke tests; inspect metadata, license, README, and dependencies.
3. Verify remote CI across all 16 OS/Python combinations and record result links.
4. Exercise a real terminal: completion, scrolling, progress/errors, slow-I/O
   cancellation, and exit cleanup. Test RTU/ASCII on physical adapters/devices;
   record OS, Python, adapter/device, revision, and outcomes.
5. Confirm trusted-PyPI publisher/environment setup, changelog date, and release
   approval before tagging. Verify artifacts, attestations, GitHub prerelease
   classification, and fresh installation after publication. Never reuse a
   published version.
6. Before stable 1.0, adopt the tested stable ctui 1.0 release, update package
   version/lockfile/changelog, and repeat the release gates.

No implementation blocker is established. Release readiness lacks verified
remote results and recorded manual hardware/terminal checks.

## Deferred scope

Polling, tags, device cloning/simulation, proxies, raw/fuzzy requests, tunneling,
and historian integration remain deferred. TLS was initially outside the
migration and then explicitly requested and completed; do not list it as pending.
ctui's optional job manager and typing-marker ideas are not ctmodbus commitments.

## Validation record

- September 13 initial migration: 34 tests passed on Python 3.11 and 3.14;
  formatting, imports, pylint, lock validation, builds, and isolated wheel/sdist
  smoke checks passed. See [MIGRATION.md](../MIGRATION.md).
- September 13 TLS/workflow follow-up through `426048a`: the local session
  reports 45 tests passing, quality checks, workflow syntax/matrix/tag/changelog/
  prerelease-script checks, and both distribution smoke tests. This supersedes
  the initial 34-test count, not the outstanding hardware/remote gates.
- September 18 memory task: documentation only; content reconciled against
  transcripts, Git history, code, tests, workflows, and ctui memory files.
  Runtime tests were not rerun. Local Markdown links and whitespace were checked.

## Open questions and laptop handoff

- Which features are still in progress or planned, and which should be next?
  The owner confirmed feature work is ongoing but has not listed the tasks.

Before switching laptops, update these notes and commit/push the working branch;
pull that branch on the receiving laptop and read root AGENTS.md first.
Uncommitted/unpushed files and local chat history do not transfer through Git.
