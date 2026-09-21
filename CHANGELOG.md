# Changelog

## [1.0.0rc1] - Unreleased

- Show USB manufacturer and product metadata in serial-device completions.
- Add project-scoped typed tags with Boolean, signed/unsigned integer, and
  floating-point decoding; configurable byte/word order; tagged reads/writes;
  and atomic TOML import/export.
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

Breaking changes: no pre-1.0 API, command, or storage compatibility. Commands use
plural snake_case data names, comma-separated write values, and separate host
and `--port` arguments. Read counts are expressed as inclusive address ranges;
`--max-count` controls request chunk size. Remove the development `debug eval`
command. Python 3.8–3.10 are no longer supported.
