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
model. Use singular table names in `tags create` because it accepts one starting
address; persisted definitions retain canonical plural Modbus table names.
With no names, read all tags in stable name order; otherwise preserve requested
order and duplicate names. Allow overlapping tags with a creation warning.
Export deterministic versioned TOML, adding `.toml` when absent; validate
imports completely and apply them atomically. Existing names require a
collision-specific TUI confirmation or explicit `--replace`. Keep file
operations within the tag command group as `tags export` and `tags import`; both
use ctui's shared path completer.

Accepted naming update, 2026-10-06: rename the management command group from
`tag` to `tags` at the owner's request. Keep `read tags`, `write tag`, and
`serve data set tag` unchanged because they name their existing I/O operations.
Do not register a separate singular management alias; ctui's ordinary command
prefix matching still applies.

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

- Resolved 2026-10-02: multi-tag reads hold one operation reservation and retain
  completed decoded rows on later failure/cancellation. A shared reserved-read
  helper preserves response checks and raw operation records. Adjacent-read
  batching remains unimplemented; device values can change between requests.
- Resolved 2026-10-02: import dispatch reserves the active project and tag edits
  before confirmation, using ctui argument parsing (including command prefixes).
  It retains validated content per task and applies that exact content. Concurrent
  tag edits/project changes are rejected; cancellation releases the guard.
- Import applies all rows in a short synchronous transaction on a separate SQLite
  connection, with no cancellation checkpoints during the transaction and no
  busy wait. This prevents ctui's shared-connection commits from exposing partial
  imports. Cancellation before application leaves tags untouched; after commit
  all imported rows remain. Metadata touch is still separate. Full reset still
  clears the tag table separately after ctui's reset.
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

## D13 — Independent servers, sparse emulation, proxy routing and evidence views

Accepted, 2026-10-03, from the owner-directed design in this session.

Add one independent server alongside the existing single client. Support TCP,
UDP, native TLS, RTU and ASCII, with local bind defaults 5020/8020. Serial serving
is an addressed device, not a tap. Use shared CTUI dispatch and an explicit
foreground option for long-running CLI serving. Stop/drain before project changes.

Persist versioned server definitions in project configs, merge referenced shared
project tags, and keep runtime data/observations separate. Defaults expose all
four 0–65535 tables, false/zero; imported omitted tables are unavailable. Each
configured table chooses illegal-unmapped or default-backed addresses. Raw ranges
and typed tags support static, random and read/time sequence rules. Keep sparse
values, coherent typed request samples, reproducible seeds and reset behavior.

Use optional trusted companion Python hooks on_read/on_write/on_tick with a
small decoded-tag get/set API. Request hook failures roll back pending state and
return exception 04; tick failures retain prior state. Confirm differing project
tag definitions, apply the exact confirmed data, and atomically store definitions
and tags. Configuration must be stopped for edits; no dynamic rule language yet.

Proxy enable requires both endpoints and zero upstream retries. Capture routing
mode per request, preserve downstream transaction/unit identities, translate
framing through PyModbus, serialize full upstream exchanges with console I/O,
and forward exceptions without simulated fallback. Server-unit requests map to
connection unit; unsupported functions return 01. Keep separate upstream and
presented observations, distinguishing read evidence, write acknowledgement and
uncertainty. Observations reset on fresh sessions and are not persisted. MITM
request/response seams exist, but rules and separate MITM TOML remain deferred.

The detailed command/config/hook contract is in [SERVER.md](SERVER.md).

## D14 — Fixed-cadence polling and appended evidence rows

Accepted at the owner's request, 2026-10-06.

One runtime poll belongs to each application. `poll tags` snapshots all or
explicit ordered tags; `poll raw` accepts ordered table options and inclusive
ranges. Keep protocol limits, response validation, project isolation, and one
serialized connection. Reserve a whole cycle, then release between cycles so
manual device commands can proceed. Never queue polling behind busy device work.

Use a monotonic fixed cadence, starting immediately. Skip busy or obsolete ticks
rather than overlap requests, cancel at each deadline, or accumulate catch-up
work. Count means started cycles; duration limits cycle starts. Both limits work
in terminal and browser sessions; CLI streams and waits for completion. Exact
wire timing is not guaranteed by the event loop or transport.

Append a header and one compact line per cycle to shared output. Preserve target
order/repetitions and display typed tags, contiguous raw bits, and four-digit raw
hex registers. Mark failed columns with ERR, retaining confirmed raw chunks and
operation records. Continue after column errors while the transport is usable;
stop on connection loss. A latest-values-only view was superseded by the owner's
explicit preference for every row, including unchanged values.

Keep stable project/tag/connection targets through preparation and execution;
reject tag mutations during polling. `poll status` retains counters and reason
after completion. `poll stop` drains gracefully; cancel/close/shutdown cancel
polling and close the connection. Poll tasks and plans are runtime state only.

Accepted display refinement: use `#` for the polling counter and ` | ` between
all columns. Preallocate widths from labels, integer bounds, float precision,
and full raw range lengths. Right-align counters/numeric tags and left-align
booleans/raw sequences. Float32/64 use 9/17 significant digits to retain
round-trip precision in a compact representation. Widen overflowing columns and
repeat the header before the affected row; do not rewrite previous output.

## D15 — Independent server and proxy request display

Accepted at the owner's request, 2026-10-06.

Append one incoming-request line per decoded server PDU and another when proxy
forwarding starts, sharing an application-local monotonic request ID. Log server
arrival before queuing and proxy dispatch after unit mapping. Show UTC timestamps,
peer/upstream, unit, function/range, and bounded write previews; retain full writes
in server records. These lines describe attempted activity, never success.

Default both routine streams on. Each enabling command has `--quiet`, and live
`serve logging` / `proxy logging` switches independently control them. Errors
remain visible when quiet; record collection is unaffected. Settings are runtime
state, reset by each enabling command. Use a shared synchronous output append
helper for polling and logs so no await interleaves updates to existing output.
Do not reinstate the reverted append default for all command results. MITM output
remains future work, without rules or extra feature scope in this implementation.

## D16 — Component commands, selected client settings, and strict TOML

Accepted and implemented, 2026-10-06, by explicit owner direction. This
supersedes the command spellings in D11, D13–D15; their I/O and evidence policies
otherwise remain in force.

Larger commands follow **component → action → transport or target**.
Use client start tcp/udp/tls/rtu/ascii, client discover, client stop,
and client status; use parallel server start/stop/status and proxy
start/stop/status. Client stop replaces both close and cancel. Status combines
lifecycle information and retained runtime evidence. Saved server definitions
belong under server config, companion hooks under server hook, and runtime
reset is server reset --confirm. Logging switches remain component-specific.
Ordinary read/write/poll syntax stays short.

Client settings are selected independently from live I/O. Client config
provides show/set/save/load; loading requires a stopped client and explicit
client start. Editing only supplied fields validates the full result before
replacement. Initial selection requires transport/target; TLS starts with port
802, serial with a one-second timeout. Show identifies saved source and unsaved
changes. Explicit start settings replace selection; stop retains it and project
transitions clear it. Certificate contents and live clients/tasks are never
stored. TLS paths have explicit clear flags and insecure mode accepts true/false.
ctui-owned config fields and built-in commands are unchanged.

Proxy start requires both endpoints and zero upstream retries. Component stops
require confirmation while proxy routing is active; rejection preserves both
components, approval stops proxy routing with the chosen endpoint. CLI supplies
--confirm; TUI/WUI use the requesting interface's confirmation dialog. Dispatch
reserves stop approval across awaits to prevent competing lifecycle transitions.
Unexpected upstream loss still fails without local fallback. Server runtime
reset preserves saved configuration and timestamped historical observations.

Bare client/server/proxy open concise example overviews in help popups; CLI
prints the same text. Generated help COMPONENT remains available. ctui's
internal help-result presentation protocol is isolated in component_help.py;
release validation must exercise it against the intended published ctui build.

No legacy aliases or TOML migrations are retained because these features are
unreleased. Framework unique command prefixes remain available (serve can
resolve as a prefix of server, rather than an explicitly registered alias).
Server files require format ctmodbus-server and integer version 1; tag files
require ctmodbus-tags and integer version 1. Unknown nested/top-level fields
fail with actionable errors. Hook tick_seconds becomes tick_interval_seconds;
server version stays 1 because the feature is unpublished. Existing server
definitions need explicit format/key updates, or clear/reimport.

Client and proxy command mixins now live in client_commands.py and
proxy_commands.py; server commands remain in server_commands.py. App.py
owns shared dispatch arbitration, projects, records, progress and shutdown.
Transport validation/factories and request routing remain in their existing
modules, preserving serialization and protocol evidence contracts.

## D17 — Management result popups and CLI server keepalive

Accepted and implemented, 2026-10-06, by explicit owner direction. This supersedes
D13's explicit foreground option and ordinary management result presentation.

Use standard ctui MessageDialog popups for owned start/stop/list/show/status,
import/export, discovery, validation, configuration set/save/load, tag edits,
server rule/hook edits, logging controls, reset, and clear. Descriptive titles,
scrollbars and unwrapped terminal text support reference tables. Actions finish
before presentation; modal dismissal gates later input without blocking async
servers, proxy exchanges, polling or output appends. Concurrent already-running
commands serialize their result dialogs; shutdown cancels pending presentations.
Existing confirmation dialogs precede the action. Errors and component help
retain their standard ctui presentation. Do not change ctui-owned commands.

Read/write results, polling rows and request logs remain in the main output.
CLI and headless dispatch preserve plain result text. The result policy and
standard widget call are isolated in result_popups.py; no custom widgets or
browser styles are introduced.

Remove --foreground from all transports/interfaces. Start always returns after
binding. CLI executes all supplied commands, then keeps a still-running server
alive after a successful sequence. A sequence stopping the server exits normally.
The first expected/unexpected command error, or explicit exit, skips keepalive
and cleans up all services with existing exit status semantics. Cancellation
also drains services and closes project storage. The application implements
keepalive before shutdown through its lifecycle hook, retaining ctui's parsing,
sequential execution, error formatting, and backend ownership. Console Ctrl-C
finishes async cleanup and exits 130 without printing a traceback.
