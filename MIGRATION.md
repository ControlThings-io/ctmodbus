# ctmodbus 1.0 migration

Target: ctui 1.0.0rc1, Python 3.11+, native async PyModbus.
No compatibility layer for pre-1.0 commands or storage.

Commit milestones:

1. Packaging and application foundation.
2. Async connection lifecycle and discovery.
3. Typed commands, range reads, and acknowledged writes.
4. Project profiles, records, progress, and cancellation.
5. Automated regression and transport integration coverage.
6. Documentation, CI, distribution validation, and release checklist.

Retain TCP/UDP/RTU/ASCII, discovery, identification, four read types, and
coil/register writes. Repair existing multi-write and response-validation gaps.
Defer polling, tags, simulation, proxying, raw/fuzzy requests,
tunneling, and historian integration.

Release gates: command parity in TUI and CLI; nonblocking I/O; serialized
connection operations; bounded shutdown; project isolation; regression and
local transport tests; installed wheel/sdist smoke tests. Serial hardware and
interactive terminal checks must be recorded separately from automation.

## Implemented

All six milestones are implemented. The package remains at 1.0.0rc1 with
ctui==1.0.0rc1 and pymodbus[serial]>=3.15.0,<3.16 (locked to 3.15.0).
The new README documents the breaking command syntax and connection defaults.

Local validation completed on Linux:

- 34 automated tests passed on Python 3.11 and Python 3.14.
- Actual TCP/UDP and bridged-PTY RTU/ASCII exchanges passed.
- Injected-terminal TUI and sequential CLI/command-file execution passed.
- Cancellation, write uncertainty, project isolation, and recording failures
  have regression coverage.
- Black, isort, pylint, and lockfile validation passed.
- Wheel and source distribution built; both passed isolated installation,
  entry-point help, and project/config smoke checks.

The GitHub workflow defines Python 3.11–3.14 checks on Linux, macOS, and Windows,
with distribution smoke tests required before publication. Those remote jobs
have not been run from this workspace. Physical serial hardware and real
terminal usability checks remain on RELEASE_CHECKLIST.md. No release was
published and no tags were pushed.

## TLS follow-up

Added native async `connect tls` after the initial migration, with server
verification, custom trust roots, optional client certificates, and profile
persistence. TLS integration uses ephemeral OpenSSL certificates and covers
verified reads/writes, mutual TLS, trust and hostname failures, and explicit
insecure connections.
