# Changelog

## [1.0.0] - 2026-10-24

### Added

- Web UI and scriptable CLI alongside the terminal UI, with shared commands,
  completion, and generated help.
- Verified Modbus TLS connections, private CA support, optional client
  certificates, and an explicit insecure mode.
- Named project tags with Boolean, integer, and floating-point types,
  configurable byte/word order, typed reads/writes, and TOML import/export.
- Confirmed bulk tag deletion, with an option to remove referenced server rules
  in the same transaction and warnings for retained Python hooks.
- Polling of tags or raw address ranges with interval, count, and duration
  settings. Results append a row per cycle; busy ticks are skipped.
- Independent TCP, UDP, TLS, RTU, and ASCII servers with sparse address maps,
  static/random/sequence values, Python hooks, config validation, and reset.
- Proxying between any supported client/server transports, with separate
  upstream and downstream status views.
- Correlated server/proxy request logs, independent quiet settings and live
  logging switches, bounded write previews, and full payloads in records.
- USB manufacturer and product details in serial-device completion.

### Changed

- Move device I/O to native async PyModbus 3.15 clients and use stable
  `ctui==1.0.0`. Each app owns one client connection and serializes device work.
- Organize lifecycle commands under `client`, `server`, and `proxy`, with
  start/stop/status commands and short component overviews.
- Save and load client settings independently of the connection. Loading selects
  settings; `client start` connects. Invalid edits leave the selection intact.
- Keep configs, tags, command history, and decoded operation records in projects.
  Live clients, tasks, and runtime status remain separate from saved data.
- Show management results in scrollable terminal/web popups while background
  polling, serving, and request logging continue. CLI results stay plain text.
- Keep CLI servers alive after a successful command sequence. Later commands
  run before keepalive; errors, exit, and Ctrl-C clean up both endpoints.
- Accept mixed decimal, hexadecimal, binary, and octal register-write lists,
  including signed 16-bit values. Preserve unsigned values and single-request
  write limits.
- Use strict, versioned TOML for tags and server definitions, with clear errors
  for unknown keys and unsupported formats.
- Consolidate package metadata and align it with the existing GPL-3.0-or-later
  source license.

### Fixed

- Validate response lengths and write acknowledgements. Preserve partial reads
  and report uncertain writes instead of implying success or safe retry.
- Handle multi-value writes and sparse device-identification responses correctly.
- Reserve the connection across multi-tag reads. Keep completed results after
  failure or cancellation and identify failed or unread tags.
- Import the exact tag data approved during confirmation and apply all rows or
  none. Guard project/tag changes while approval and import are in progress.
- Keep protocol records in the project that started the operation. Report
  recording failures separately from acknowledged device writes.

### Compatibility

- Require Python 3.11 or newer. Python 3.10 and earlier are no longer supported.
- This release breaks compatibility with 0.x APIs, commands, and storage. Use
  component lifecycle commands; old spellings aren't retained as aliases.
  Unique command prefixes still work.
- Raw reads/writes use plural table names, inclusive read ranges, comma-separated
  write values, and separate host and `--port` arguments. `--max-count` limits
  each read request, not the total address count.
- Remove `debug eval` and server `--foreground` options. CLI serving now uses
  automatic keepalive.
- Older development TOML files need the current format/version markers and
  `tick_interval_seconds` hook setting. There is no automatic format migration.

See [README.md](README.md) for current usage and [MIGRATION.md](MIGRATION.md)
for the transition from 0.x.
