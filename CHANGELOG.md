# Changelog

## [1.0.0rc1] - Unreleased

- Append output from all ctmodbus-owned tag, connection, server and proxy
  commands; retain ctui built-in command behavior.

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
- Add `connect tls` with verified server certificates, custom CA roots, optional
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
