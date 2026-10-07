# Changelog

## [1.0.0rc1] - Unreleased

- Present ctmodbus management results in standard scrollable TUI/WUI popups,
  preserving main output while device work and request logging continue.
- Remove server --foreground options. CLI now runs the full command sequence,
  then keeps remaining listeners alive; errors, explicit exit, and interruption
  clean up server and client resources.

- Refactor unreleased commands into client/server/proxy component groups, with
  start/stop/status, separate configuration and runtime views, and example
  help popups. Remove old command spellings; ctui-owned commands are unchanged.
- Add selected client configuration show/set/save/load, explicit start after
  load, atomic editing, and proxy-aware component stop confirmations.
- Require strict TOML format/version markers and actionable unknown-key errors;
  add the server format marker and rename hook tick_interval_seconds without
  changing server version 1.

- Display correlated server-arrival and proxy-forwarding request lines by default,
  with per-transport/proxy `--quiet`, independent live logging switches, visible
  failures, bounded write previews, and full write payloads in server records.

- Add fixed-cadence `poll tags` and multi-table `poll raw` with configurable
  intervals, count/duration limits, status and graceful stop. Append compact
  aligned typed/raw rows with a `#` counter in terminal and browser sessions,
  retain partial read evidence,
  and skip busy ticks without overlapping or accumulating device requests.

- Add independent TCP/UDP/TLS/RTU/ASCII serving, project-scoped TOML definitions,
  sparse table defaults, typed static/random/sequence rules, transactional Python
  hooks, validation, export and runtime reset commands.
- Add serialized cross-transport proxying and separate client/downstream
  observation views, retaining write uncertainty and decoded operation records.

- Import the exact confirmed tag data, guard project/tag changes during import,
  and apply tag merges in an isolated all-or-none transaction.

- Reserve the connection across multi-tag reads and preserve completed decoded
  results on failure or cancellation, identifying failed and unread tags.

- Show USB manufacturer and product metadata in serial-device completions.
- Add project-scoped typed tags with Boolean, signed/unsigned integer, and
  floating-point decoding; configurable byte/word order; tagged reads/writes;
  and atomic TOML import/export with path completion through `tags export` and
  `tags import`.
- Add `client start tls` with verified server certificates, custom CA roots, optional
  client identity, explicit insecure mode, and persisted TLS connection settings.

- Migrate from ctui 0.x to ctui 1.0.0rc1 and require Python 3.11+.
- Use native async PyModbus 3.15 clients for TCP, UDP, RTU, and ASCII.
- Replace global runtime state with an application-owned connection lifecycle.
- Adopt typed commands, inclusive integer ranges, named options, automatic CLI,
  completion, project history, connection profiles, and decoded protocol records.
- Serialize device operations, report read progress, and add explicit cancellation.
- Check response lengths and write acknowledgements; report partial reads and
  uncertain writes; repair multi-value writes and sparse device identification.
- Replace obsolete manual server scripts with one current fixture and automated
  command, transport, persistence, cancellation, and terminal tests.
- Consolidate packaging and align license metadata with the GPL-3.0-or-later source.

Breaking changes: no pre-1.0 API, command, or storage compatibility. Raw reads
and writes use plural snake_case names, comma-separated values, and separate host
and `--port` arguments. Read counts are expressed as inclusive address ranges;
`--max-count` controls request chunk size. Remove the development `debug eval`
command. Python 3.8–3.10 are no longer supported.
