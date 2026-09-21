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
Use plural snake_case names for raw reads/writes, comma-separated values, and
explicit named options. Host and port are separate, including IPv6. Do not restore old
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

Accepted, 2026-09-18; scope refined 2026-09-20 and 2026-09-21.

Keep project constraints and context locations in AGENTS.md, current work and
validation gaps in STATUS.md, and durable project rationale here. Track these
files with the branch for laptop continuity. Personal development preferences
belong in `~/.codex/AGENTS.md` and need separate synchronization between machines.

Keep STATUS focused on actionable state; Git preserves completed milestones and
prior evidence reviews. Read relevant decisions on demand rather than requiring
the entire log for every task. Retain technical boundaries and rationale so
context savings do not depend on rediscovering correctness constraints.

The September 21 owner-approved documentation policy places local implementation
contracts in docstrings, shared architecture and unresolved discrepancies here,
current work/evidence in STATUS, usage in README, and release procedures in
RELEASE_CHECKLIST. MIGRATION remains a short compatibility guide; CHANGELOG
retains release-facing history. These complementary files link to authoritative
locations instead of duplicating contracts or current validation claims.

## D11 — Project-scoped typed tags

Accepted and implemented, 2026-09-20.

Tags map a project-local name to a Modbus table, first zero-based address, and
type; the type derives the address count. They are independent of connection
profiles, hosts, and unit IDs, and use whichever single connection is active.
Support Boolean, signed/unsigned 8/16/32/64-bit integers, and IEEE 32/64-bit
floats. Boolean tags use coils or discrete inputs; numeric tags use input or
holding registers. Writes remain limited to coils and holding registers.

Register tags default to big byte order within each 16-bit register and little
word order across registers, with named options for both. Eight-bit values use
one full register: big byte order puts the value in the low byte, little byte
order in the high byte, and writes zero to the unused byte. This avoids an
unsafe read-modify-write. Reject non-finite floats. Accept natural typed values
and radix-prefixed integers without requiring ctui `HexBytes`. For signed types,
interpret unsigned binary/octal/hex literals as fixed-width two's-complement bit
patterns; signed and decimal literals retain their numeric meaning. Negative
positional values use ctui's standard `--` end-of-options marker.

Use comma-separated names for `read tags` to fit ctui's typed-list command
model. Use singular table names in `tag create` because it accepts one starting
address; persisted definitions retain canonical plural Modbus table names.
With no names, read all tags in stable name order; otherwise preserve requested
order and duplicate names. Allow overlapping tags with a creation warning.
Export deterministic versioned TOML, adding `.toml` when absent; validate
imports completely and apply them atomically. Existing names require a
collision-specific TUI confirmation or explicit `--replace`. Keep file
operations within the tag command group as `tag export` and `tag import`; both
use ctui's shared path completer.

Tagged I/O reuses the existing serialized read/write path, response checks,
recording, cancellation, and uncertain-write reporting. Tag definitions are
included in whole-project snapshots and cleared by a full project reset.

Superseded alternatives: explicit end-address ranges became type-derived widths;
the initial little-byte proposal became big bytes/little words; raw HexBytes
input was dropped in favor of typed numeric parsing; whitespace tag lists became
ctui comma-separated lists; creation table names became singular. No permanent
unit/host association is stored, including for a possible future multi-connection
model; any such association would be session-local and is not implemented.

## D12 — Implementation discrepancies and ctui proposals

Audit findings, 2026-09-21, against `4718ddd`; unresolved, not new accepted policy.

- D02's whole-operation serialization and D04's partial-read reporting do not
  fully extend across a multi-tag read. `TagCommandMixin.read_tags` reserves one
  tag at a time and discards earlier displayed rows on later failure. Earlier
  planning suggested adjacent-read batching and retained completed tags; neither
  is implemented. Stored raw records still contain completed exchanges.
- `ModbusApp.prepare_tag_import` runs before lifecycle guards, matches only the
  full command spelling, and rereads the file after confirmation. Tag commands
  are not in the device-task guard set. Concurrent project changes or modified
  import files can therefore invalidate the state that was confirmed.
- `TagStore.import_all` rolls back ordinary exceptions, but cancellation bypasses
  that handler. Other services share its SQL connection and can commit during
  awaits; atomic imports depend on noninterleaving use. Full reset clears the tag
  table in a separate step after ctui's reset, rather than one transaction.
- Tag file reads/writes run synchronously on the event loop. Export uses a fixed
  `.tmp` sibling, so atomic destination replacement is not concurrent-export
  safety. Import has no file-size limit.
- Signed radix bit patterns and negative decimal writes were checked in focused
  tests, but the history does not establish a full final-revision regression run
  after all tag follow-ups. Artifact checks likewise preceded those follow-ups.

Proposed ctui improvements, not dependency commitments: state-dependent
confirmation callbacks; application-owned project table initialization/reset/
statistics; extensible reset sections. The comma-separated tag list removed the
need for variadic CLI parameters. Keep these proposals separate from accepted
Modbus semantics. Contract docstrings describe current behavior; resolving the
discrepancies requires implementation work and regression checks.
