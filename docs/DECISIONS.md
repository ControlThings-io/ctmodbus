# Project decisions

Recorded 2026-09-18 from the September 13 migration discussion, authorized plan,
and implementation history through `426048a`; owner clarifications date from
September 18. Dates below identify original decisions. “Accepted” means owner
direction or an authorized plan; “Implemented policy” does not imply the owner
specified every detail. Read entries relevant to the task, using their headings.

## D01 — Migrate the existing feature set without 0.x compatibility

Accepted, 2026-09-13; `c225522` through `7914437`.

Prepare for 1.0 using ctui 1.0.0rc1, make I/O async where possible, and take
advantage of the framework's typed commands, CLI, persistence, and lifecycle.
The owner explicitly waived backward compatibility and prioritized migration
over additional functionality. Preserve TCP/UDP/RTU/ASCII, discovery, device
identification, all four read types, and coil/holding-register writes.

Remove legacy command/storage compatibility and the development `debug eval`
command. Repair existing broken multi-writes, unchecked replies, sparse device
identification, and range ambiguity. Defer the expansion items in STATUS.
This migration-specific waiver is not a future blanket compatibility policy.

## D02 — Native async clients and application-owned state

Accepted migration architecture, 2026-09-13; `39d0633`, `500949f`.

Use native PyModbus async clients instead of wrapping synchronous device I/O.
One ModbusApp owns its connection, settings, and tasks; replace import-time
global application/unit state. Serialize whole device operations and connection
changes; reject queued work from an obsolete connection generation.

Offload serial enumeration, process inspection, and later TLS certificate loading
with `asyncio.to_thread`; retain synchronous pure parsing/formatting. Bound
requests and drain/cancel outstanding work at shutdown. Explicit `cancel`/`close`
closes the transport, requiring reconnection; do not automatically reconnect.
These boundaries keep the UI responsive and avoid stale replies or operations
silently acting on a replacement connection. Ctrl-C clears input through ctui;
it is not the device-work cancellation command.

## D03 — One typed command path for TUI and CLI

Accepted migration design; implemented policy, 2026-09-13; `b5dabf8`.

Use CtuiApp, public `@command`/`Argument` APIs, `IntegerRanges`, typed lists,
CommandError, and CommandResult. TUI and sequential `-c`/`-f` CLI share dispatch.
Use plural snake_case data names, comma-separated write values, and explicit
named options. Host and port are separate, including IPv6. Do not restore old
aliases, host:port parsing, or space-separated multi-write values.

Addresses are zero-based wire addresses 0–65535. Read ranges are inclusive,
preserve order and repetitions, and accept at most 65,536 addresses. `--max-count`
limits a request, not total addresses: 2,000 bits or 125 registers. Multi-writes
are one request, never silently split (1,968 coils or 123 registers maximum).
Validate the full requested range/value set before device I/O.

## D04 — Report protocol evidence accurately

Accepted correctness goals; implemented policy, 2026-09-13; `b5dabf8`, `500949f`.

Validate response functions, lengths, values, and write echoes/counts before
reporting success. A matching write acknowledgement is not independent readback.
Failed/interrupted writes may have taken effect; explicitly distinguish an
unconfirmed outcome from a write never sent. Default retries are zero.

Keep completed values when a later read chunk fails. Handle sparse/continued
identification and reject invalid continuation. Render UTC timestamps and
compressed address/value summaries consistently in both interfaces; escape
terminal controls. Register characters represent Unicode code points, not UTF-8
decoding. Append output with CommandResult rather than stale output snapshots.

## D05 — Project-scoped profiles and decoded records

Accepted framework integration; implemented policy, 2026-09-13; `c6054e2`,
`500949f`, `7914437`.

Use ctui services under stable app ID `io.controlthings.ctmodbus`: configs for
named connection profiles, records for attempted requests/decoded responses/
errors grouped by connection session, and project command history. Live clients
and tasks remain runtime state. Provide tcp-local/udp-local profile templates.

Require closed connections and finished device work before changing/resetting
projects, and finish recording sessions in their original project. This prevents
cross-project records. Records are decoded operations, not raw packet capture.
Storage warnings must not turn acknowledged writes into apparent protocol
failures and prompt accidental retries. History follows ctui's successful-command
policy; protocol errors remain available in records.

## D06 — Packaging and dependency baseline

Accepted migration plan; implemented policy, 2026-09-13; `c225522`.

Require Python 3.11+ to match ctui. Pin `ctui==1.0.0rc1` for the migration and
constrain PyModbus to the tested 3.15 minor series, locking 3.15.0. The recorded
rationale for the minor bound is PyModbus API changes between minor releases.
Do not expand it without compatibility validation.

Use pyproject.toml as package/version metadata, uv_build, and uv.lock; remove
obsolete setup.py and VERSION duplication. Align metadata with the existing
GPL-3.0-or-later source/license; this was not a new relicensing decision.

## D07 — TLS added by explicit follow-up

Accepted, 2026-09-13; `ac4af8d` (formerly `504ffa6` before commit rewording).

The owner requested `connect tls` after the baseline migration. Use native
Modbus TLS framing with default port 802. Verify trust and hostname by default,
support private CA roots and optional client identity, and require explicit
`--insecure` to disable verification. Persist file paths/settings, never key or
certificate contents; referenced files must exist on the reconnecting machine.
Current key loading requires unencrypted keys. Integration tests use ephemeral
OpenSSL certificates for verified I/O, mutual TLS, and rejection cases.

## D08 — Release candidate first, ctui-aligned release workflows

Accepted, 2026-09-13; `4fcc4f2`, `426048a`.

The owner explicitly set the next intended release to `v1.0.0rc1`, with package
version `1.0.0rc1`, rather than immediately publishing stable 1.0. The migration
plan requires adopting tested stable ctui before final ctmodbus 1.0.

At the owner's request, align build/test/publish workflows with ctui while
retaining ctmodbus source paths and pylint. Test Python 3.11–3.14 on Linux
x86-64/ARM64, Windows, and macOS. Build and smoke-test wheel and sdist, upload
tested artifacts, validate tag/version equality, attest, and use trusted PyPI
publishing. GitHub release notes combine curated changelog and generated notes;
prereleases are marked prerelease and never latest.

Follow the release checklist and obtain release approval before publication.
Local passing tests do not prove remote CI, real-terminal usability, or physical
serial timing/driver behavior. This decision does not assert publication occurred.

Owner update, 2026-09-18: ctmodbus RC1 is not published; feature development is
still ongoing. Release validation follows that work. The specific remaining
features have not been listed, so do not invent commitments from deferred ideas.

## D09 — Migration commit history

Accepted, 2026-09-13.

The owner authorized rewording this branch's migration commits to Conventional
Commits. The hashes above identify the resulting history;
`backup/pre-conventional-commits-504ffa6` preserves the earlier seven commits.
This is not unfinished implementation or standing authorization to rewrite
future shared history. General commit preferences live in global instructions.

## D10 — Project memory and instruction scope

Accepted, 2026-09-18; scope refined by owner request, 2026-09-20.

Keep project constraints and context locations in AGENTS.md, current work and
validation gaps in STATUS.md, and durable project rationale here. Track these
files with the branch for laptop continuity. Personal development preferences
belong in `~/.codex/AGENTS.md` and need separate synchronization between machines.

Keep STATUS focused on actionable state; Git preserves completed milestones and
prior evidence reviews. Read relevant decisions on demand rather than requiring
the entire log for every task. Retain technical boundaries and rationale so
context savings do not depend on rediscovering correctness constraints.
