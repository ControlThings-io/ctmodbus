# Migrating from ctmodbus 0.x

The 1.0 migration deliberately breaks compatibility with 0.x commands and
storage. The dependency baseline and architectural rationale are in
[docs/DECISIONS.md](docs/DECISIONS.md).

Use [README.md](README.md) for installation, command syntax, connection
defaults, profiles, and tags. In particular:

- Supply host and port separately; use `--port` instead of `host:port` syntax.
- Use plural table names for raw reads/writes, inclusive read ranges, and
  comma-separated write values. `tag create` uses singular table names.
- Close the active connection before opening another or switching projects.
- Use project-scoped profiles and decoded records; old storage has no
  compatibility layer. The former `debug eval` command is removed.

TLS and typed tags were added after the initial six migration milestones;
their original deferral is superseded by D07 and D11 in the decision log.
[CHANGELOG.md](CHANGELOG.md) records user-facing additions. Git history retains
the completed milestone sequence.

Current work and dated validation evidence belong in
[docs/STATUS.md](docs/STATUS.md). Follow
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for release procedures; historical
local results do not establish current release readiness or publication.
