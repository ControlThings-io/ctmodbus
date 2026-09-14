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
Defer TLS client, polling, tags, simulation, proxying, raw/fuzzy requests,
tunneling, and historian integration.

Release gates: command parity in TUI and CLI; nonblocking I/O; serialized
connection operations; bounded shutdown; project isolation; regression and
local transport tests; installed wheel/sdist smoke tests. Serial hardware and
interactive terminal checks must be recorded separately from automation.
