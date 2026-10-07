# Project status

Last reconciled: 2026-10-07, `dev-v1.0.0` at `f0cdb23`, with local confirmed
bulk tag deletion and atomic server tag-rule removal. Changes remain uncommitted.

## Current state

- Async migration, TLS, project-scoped typed tags (`5eb04ee`), and USB identity
  in serial completion (`4718ddd`) are implemented. Architecture and accepted
  choices are in [DECISIONS.md](DECISIONS.md).
- Version remains `1.0.0rc1`; dependencies are `ctui==1.0.0rc1` and
  `pymodbus[serial]>=3.15.0,<3.16` (locked to 3.15.0), Python >=3.11,<4.
- During development, local commands and tests use the adjacent `../ctui`
  checkout through `uv run --with-editable ../ctui`. This temporary override
  leaves dependency metadata unchanged. Release validation must use the chosen
  published PyPI ctui version without the override.
- IDEs using `.venv/bin/python` need the adjacent checkout installed directly
  with `uv pip install --python .venv/bin/python --editable ../ctui` after
  `uv sync`. The run-time override alone uses a separate environment. See the
  [development setup](../README.md#installation).
- The owner reported RC1 unpublished on September 18. Remote refs, CI, and
  publication state have not been refreshed; CHANGELOG remains Unreleased.
- The September 21 audit updates global documentation ownership rules, expands
  contracts throughout all 16 project Python files, and reconciles all seven
  Markdown files. Global instructions need separate synchronization per machine.
- Resolved and remaining tag lifecycle/concurrency discrepancies are recorded in
  [D12](DECISIONS.md#d12--implementation-discrepancies-and-ctui-proposals).
- Tag TOML commands are grouped with the other tag-management commands as
  `tags export` and `tags import`; the unreleased `export tags` and `import tags`
  spellings are not retained as aliases. Both path arguments use the shared
  ctui path completer from the adjacent development checkout.
  The management group is now `tags` (create/list/show/rename/delete/export/
  import); dispatch guards, tests, and examples use that spelling. `write tag`
  and server tag I/O retain their existing syntax. See D11 for the naming decision.

- Server/emulator commands, all five transports, TOML and terminal definition
  editing, typed/random/sequence rules, optional Python hooks, plain proxying,
  and independent client/downstream evidence views are implemented locally.
  See [SERVER.md](SERVER.md), [D13](DECISIONS.md#d13--independent-servers-sparse-emulation-proxy-routing-and-evidence-views),
  and the pump/tank example under `examples/`. MITM rules remain deferred.

- Fixed-cadence `poll tags` and multi-table `poll raw` now run one poll per app,
  with interval/count/duration options, retained status, and graceful stop.
  Each cycle appends one aligned typed/raw row headed by `#`, with separators
  between all columns and repeated headers on width expansion. Busy ticks are
  skipped and partial reads remain recorded. CLI polling streams and waits.
  Targets are stable and client stop/shutdown stop polling. See
  [Polling](../README.md#polling) and [D14](DECISIONS.md#d14--fixed-cadence-polling-and-appended-evidence-rows).

- Server request arrivals and proxy forwarding now append correlated UTC lines
  by default. Every listener and `proxy start` support `--quiet`; independent
  live `server logging` / `proxy logging` switches suppress routine lines while
  preserving errors and operation records. Status shows logging state; write
  previews are bounded and records retain full payloads. See
  [request display controls](SERVER.md#request-display-controls) and
  [D15](DECISIONS.md#d15--independent-server-and-proxy-request-display).
- The `aad20cd` revert removed the application-wide append default. Ordinary
  management results now use TUI/WUI popups, while runtime request/polling
  lines explicitly append. Read/write output and ctui built-ins retain their
  existing presentation. See D17.

- Component commands now follow client/server/proxy start/stop/status, with
  client discover, selected client config show/set/save/load, server config/hook
  editing, and server reset. Loading settings requires an explicit client start.
  Stop confirmations protect active proxy routing; bare groups show example
  help popups. Legacy aliases are removed; ctui-owned commands/fields remain
  unchanged. Server reset retains timestamped observations. See
  [D16](DECISIONS.md#d16--component-commands-selected-client-settings-and-strict-toml)
  and [README usage](../README.md#projects-profiles-and-records).
- Server/tag TOML now require exact format/version markers and reject unknown
  nested/top-level keys. Server stays version 1 and uses `tick_interval_seconds`.
  Existing unreleased server configs need explicit format/key updates or
  clear/reimport. Client/proxy commands have dedicated modules; shared lifecycle
  arbitration remains in app.py.

- Owned management results now use standard scrollable ctui message dialogs
  with descriptive titles. Actions finish first; background logging and polling
  continue while dismissal gates new command submissions. UI output is preserved,
  confirmations remain separate, and CLI/headless results stay plain text.
- Every server start returns immediately; --foreground has been removed. CLI
  executes the full sequence, then keeps a remaining listener alive on success.
  Errors and explicit exit bypass keepalive; cancellation always cleans up both
  endpoints. The CLI entry point handles Ctrl-C without a traceback (exit 130).
  See [D17](DECISIONS.md#d17--management-result-popups-and-cli-server-keepalive)
  and [result presentation](../README.md#management-result-popups).

- `tags delete --all` now supports confirmed bulk deletion; NAME/--all are
  exclusive. Saved server tag references refuse deletion unless explicitly
  removed using --remove-server-rules. Both tables change in one transaction;
  other config and external files are retained. Hook warnings appear before
  approval. TUI/WUI use standard Yes/No confirmation and MessageDialog results;
  CLI requires --confirm for bulk/rule deletion or hook warnings. Dispatch
  reserves tag/project/server edits across preparation and approval. See
  [tag removal](../README.md#removing-tags) and D18.

## Next steps and validation gaps

1. Multi-tag serialization/partial output and tag-import confirmation, atomic
   application, and project isolation are fixed. Remaining D12 items include
   reset integration and optional file-I/O/export improvements; adjacent-read
   batching remains future work. These are not release feature commitments.
   ctui enhancements listed there remain proposals, not dependency commitments.
2. Manually exercise component overviews, option completion, client config
   editing/loading, and proxy stop confirmation in a real terminal/browser.
   Exercise tag completion, collision confirmation, and typed output in a real
   terminal; verify USB metadata on physical serial ports.
   Manually exercise sustained polling in a real terminal/browser and against
   physical devices. Automated TUI/WUI and cadence checks pass; backend test
   stalls were resolved by running outside the sandbox (see October 6 evidence).
3. Before `1.0.0rc1` release validation, select the published PyPI ctui version,
   update the dependency and lockfile if needed, and stop using the local
   editable override. Then run the [release checklist](../RELEASE_CHECKLIST.md)
   on the intended release revision, including the full platform matrix,
   artifacts, terminal checks, and physical RTU/ASCII devices. Record actual
   evidence here.
4. Obtain release approval before publication. Before stable 1.0, adopt tested
   stable ctui and repeat release gates (D08).

Device cloning, MITM rules, raw/fuzzy requests, tunneling, and
historian integration remain deferred. No implementation blocker is established;
release readiness lacks final-revision and manual/remote validation.

## Validation evidence

- October 7 tag deletion on `f0cdb23` plus the working tree, Python 3.11.16
  with adjacent ctui at `79579d0`: all 127 tests passed. New regressions cover
  bulk approval/empty selection, exclusive and unknown targets, single/bulk saved
  references, explicit rule removal, pre-approval counts/hook warnings, retained
  unrelated configuration, approval cancellation, SQL rollback on either table,
  changed-config rejection, in-flight edit protection, stopped server/polling
  requirements, and actual WUI Yes/No confirmation with MessageDialog completion.
  Existing transport, polling, popup, CLI, project and import regressions pass.
  The adjacent ctui moved configs under project configs; README and test/smoke
  references were reconciled with that inherited API, without modifying ctui.
- Black/isort checks, pylint (10.00/10), lockfile, whitespace and local document
  links passed. Wheel/sdist builds and isolated artifact smoke tests passed with
  the adjacent ctui override. Dependency metadata and lockfile are unchanged.
  IDE editable ctui imports and dependency compatibility were checked. Physical
  hardware, remote platform CI and sustained manual UI checks were not performed;
  published-ctui validation remains a release gate.


- October 6 management popups/CLI keepalive on `ea96a46` plus the working tree,
  Python 3.11.16 with adjacent ctui at `ec16fb1`: all 117 tests passed. New
  coverage exercises standard TUI popup dismissal, WUI result presentation,
  descriptive-title/owned-command scope, output preservation and live network
  request logging while a startup popup awaits dismissal, command gating and
  popup cancellation at shutdown. CLI regressions cover later commands before
  keepalive, normal stop/exit, expected/unexpected errors, cancellation cleanup,
  and a real POSIX subprocess SIGINT that exits 130 without traceback and releases
  its listener. Existing TCP/UDP/TLS/mTLS/PTY transport, proxy, polling, record,
  configuration and project isolation regressions pass.
- Black/isort formatting, pylint (10.00/10), lockfile, local documentation links
  and whitespace checks passed. Wheel/sdist builds and both isolated artifact
  smoke tests passed with the development ctui override. Dependency metadata
  and lockfile are unchanged. Remote platform CI, physical hardware and manual
  sustained browser/terminal checks were not run; published-ctui validation
  remains a release gate.


- October 6 component refactor on `5ffde8c` plus the working tree, Python
  3.11.16 with adjacent ctui at `ec16fb1`: all 111 tests passed. Coverage includes
  real TCP/UDP/TLS/mTLS and PTY RTU/ASCII clients/listeners, cross-transport
  proxying, polling, records, cancellation, project isolation, and import guards.
  A final focused run passed all 21 server/proxy tests after adding real-endpoint
  declined/confirmed stop checks; the other endpoint and forwarding are retained
  on rejection. New regressions cover selected config save/load/set without I/O, explicit
  start, atomic invalid edits, TLS clearing/verification, source/dirty state,
  completion/unique prefixes, concurrent config/stop reservations, declined and
  accepted stop confirmation, bare-component terminal/browser help presentation,
  generated references, removed aliases, strict TOML markers/nested keys, and
  retained reset evidence. Existing tests use the new command hierarchy.
- Black/isort checks and pylint (10.00/10), lockfile and whitespace checks passed.
  Wheel/sdist builds and both isolated artifact smoke tests passed with the
  development ctui override. All 22 documented server assembly/export commands
  and the example TOML import/validate/export round trip passed. Local document
  links were checked. Restored adjacent ctui editable in the IDE .venv; direct
  imports and dependency compatibility checks passed. Dependency metadata and
  lockfile are unchanged. Physical hardware, sustained manual terminal/browser
  checks, published-ctui release validation, and remote platform CI were not run.


- October 6 proxy display follow-up: proxy request lines now use `unit=<value>`,
  matching server lines while retaining the actual mapped upstream unit. The
  focused proxy logging/quiet/error regression passed; README example updated.

- October 6 request logging on `aad20cd` plus the working tree, Python 3.11.16
  with adjacent ctui at `ec16fb1`: all 101 tests passed, including actual
  TCP/UDP/TLS and PTY servers/proxying, real TUI/WUI output, and polling.
  New checks cover default arrivals, shared server/proxy request IDs, unit
  mapping, independent quiet/live switches, visible quiet-mode errors, UTC
  timestamps, escaped controls, bounded previews/full recorded write payloads,
  restart defaults, browser append preservation, and CLI stream selection.
  Black/isort, pylint (10.00/10), lockfile and whitespace checks passed.
  Dependency metadata is unchanged. Physical-device and sustained manual UI
  checks, remote matrix CI, distribution artifacts, and publication were not
  performed.

- October 6 polling alignment refinement on `b8af8e4` plus the working tree:
  all 14 focused polling tests and the real TUI test passed on Python 3.11
  with adjacent ctui. Tests cover separator positions across mixed values and
  errors, integer type bounds, full raw widths, counter/value overflow and
  repeated headers, float precision, and existing polling/CLI/WUI behavior.
  Changed-file Black/isort checks, pylint (10.00/10), and whitespace checks
  passed. The full suite result below predates this display refinement;
  unrelated transport and packaging checks were not repeated.

- October 6 polling changes on `b8af8e4` plus the working tree, Python 3.11.16
  with adjacent ctui at `216ef28`: full suite passed all 95 tests, including
  real TUI polling and TCP/UDP/TLS/mTLS/PTY transport tests. All 12 focused
  polling tests also passed. Coverage includes fixed cadence, skipped busy
  ticks, count/duration,
  ordered raw ranges/repeats, partial chunks, records, target-resolution guards,
  immediate and in-flight cancellation, graceful stop, CLI interruption and
  lifecycle/streaming,
  shared layout appends, and an actual local WUI runtime.
  The previous backend stalls disappear outside the filesystem sandbox; the
  old TUI exit test was updated for current ctui's explicit confirmation.
  Black, isort, pylint (10.00/10), lockfile and whitespace checks passed.
  Dependency metadata and lockfile are unchanged. Manual sustained browser/
  terminal and physical-device timing, remote CI, artifacts, and release
  publication were not performed.

- October 6 `tags` management rename on `759b8f7` plus the working tree:
  command-registration checks and CLI help passed with adjacent editable ctui.
  Four codec tests passed; the focused tag suite then stalled at its first
  backend-dependent test and was interrupted, consistent with the existing
  validation blocker. Black and isort checks of changed Python files passed
  through their synchronous APIs; whitespace checks passed. Full dispatch,
  import-guard and server regressions still need a completed test run.

- October 5 development environment repair on `4cb75fd`: installed adjacent
  ctui at `4833e58` editable into the project `.venv`, including its new aiohttp
  dependency. Direct Python imports resolve ctui to the adjacent source tree;
  `ctmodbus.app` imports, CLI `--help`, and `uv pip check` passed. The full
  unittest run stalled on its first test, `test_all_transport_commands`, and
  was interrupted; no suite success is claimed. Dependency metadata and
  lockfile remain unchanged. README now documents the direct editable install
  and development run overrides.

- October 3 server/emulator and proxy changes on `2c9afc7` plus the working tree:
  all 83 tests passed on Python 3.11.16 with adjacent ctui main at `fdda194`.
  New regressions cover sparse maps, address 65535, typed/partial sequences,
  random seeds, timed rules, hook rollback and ticks, import confirmation,
  lifecycle guards, actual TCP/UDP/TLS/mTLS and PTY RTU/ASCII listeners,
  cross-transport proxying and unit mapping, faithful exceptions, separate
  evidence views, pipelined transaction IDs, invalid counts and bind failures.
  CLI import/validate/export of `examples/device.toml` passed. Black, isort,
  pylint (10.00/10), lockfile and whitespace checks passed; wheel and sdist
  builds and isolated wheel/sdist smoke checks passed with the same ctui
  override. All 21 documented CTUI assembly/export commands also passed.
  Dependency metadata is unchanged. Physical hardware, remote
  CI/platform checks and publication were not performed.

- October 2 prepared tag-import changes on `920daa0` plus the working-tree diff:
  all 66 tests passed on Python 3.11.16 with adjacent ctui main at `fdda194`.
  Regressions cover changed files during confirmation, project/tag guards,
  in-flight edits, cancellation before application, and all-row SQL rollback.
  Black, isort, pylint (10.00/10), lockfile and whitespace checks passed; wheel
  and sdist builds passed. Dependency metadata remains unchanged. Physical
  serial hardware and remote platform CI were not checked.

- October 2 multi-tag read changes on `6fd5c21` plus the working-tree diff:
  all 61 tests passed on Python 3.11.16 with adjacent ctui main at `fdda194`.
  Added regressions for whole-command serialization, partial failure,
  cancellation, ordering/duplicates, and validation before I/O. Updated the
  existing responsive-help test to request ctui's grouped `help read` page.
  Black, isort, pylint (10.00/10), lockfile and whitespace checks passed.
  Local TCP/UDP, PTY serial, TLS, and terminal tests ran; physical hardware and
  remote platform CI were not checked. Dependency metadata remains unchanged.

- Historical September 13 migration through `7914437`: 34 tests reported passing
  on Python 3.11 and 3.14, local TCP/UDP and PTY serial, quality/lock checks,
  wheel/sdist builds, and isolated installed-artifact smoke checks.
- Historical TLS/workflow follow-up through `426048a`: prior session reported
  45 passing tests, quality/lock/build/workflow checks, and both artifact smoke
  tests. These supersede the initial test count, not the manual/remote gates.
- September 20 tag work based on `4e34098`: full suite reported 53 passing tests
  on Python 3.11 and passing quality/build/artifact checks before final follow-ups.
  Later singular syntax/read-all/signed-value updates had 10 focused tag tests.
  Do not treat the earlier full-suite/artifact checks as tests of final `5eb04ee`.
- September 20 serial completion based on `5eb04ee`, committed at `4718ddd`:
  30 discovery/command tests and formatting/import/lint/whitespace checks passed.
- September 21 documentation audit on `4718ddd`: Python syntax and docstring
  coverage checked; non-docstring ASTs match HEAD in all 16 Python files.
  Black, isort, pylint (10.00/10), and whitespace checks passed.
  All 40 focused command/tag/discovery tests passed; local Markdown links and
  anchors checked. Full transport/matrix and artifact checks were not rerun for
  this documentation-only change.
- September 21 tag command rename and shared path-completer integration on
  `cf3fb59`: all 11 focused tag tests passed on Python 3.11 using the adjacent
  editable ctui checkout.

## Audit source coverage

Reviewed the three locally available ctmodbus Codex session files (including
overlapping replayed history), current source/tests, all seven project Markdown
files, and relevant Git history. Earlier September 13/18 evidence is retained
from Git-tracked notes rather than claimed as newly rerun validation. Histories
only on other machines or unavailable account sessions were not accessible.
No additional project Markdown stash was found in the repository beyond those files;
private transcripts and machine-specific logs are not copied into this repository.
