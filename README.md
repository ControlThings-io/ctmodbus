# ControlThings Modbus

An asynchronous Modbus tool for functional and cybersecurity protocol testing,
built with [ctui](https://github.com/ControlThings-io/ctui) and
[PyModbus](https://github.com/pymodbus-dev/pymodbus).

Features in 1.0.0:

- Terminal UI, web UI, and scriptable CLI
- Clients and servers for TCP, UDP, TLS, serial RTU, and serial ASCII
- Device identification, reads across all four Modbus tables, and
  single/multiple coil and holding-register writes
- Named tags with automatic Boolean, integer, and floating-point conversion,
  configurable byte/word order, and tag import/export
- Client reads using address lists and ranges, consecutive writes, and
  polling of addresses or tags with interval, count, and duration settings
- Server simulation with static, random, and sequence values, optional
  Python hooks, and validated config import/export
- Proxying between any combination of the supported transports
- Runtime views of last read values and write outcomes, plus optional
  server/proxy request logging
- Saved projects with command history, configs, tags, operation records,
  and project import/export

## Installation

Requires Python 3.11 or newer. Until 1.0.0 is published, use the
[checkout setup](#development-and-validation) for the features described here.
The PyPI commands below install the latest published release.

Install from PyPI:

```bash
pip3 install ctmodbus
```

Or better yet, use `uv` to install it in an isolated environment:

```bash
uv tool install ctmodbus
```

Just trying it out? Run it with `uvx`:

```bash
uvx ctmodbus
```

Run `ctmodbus` for the terminal UI or `ctmodbus --web` for the web UI.
Web mode prints a local URL with a session token; open that URL in your browser.
Use `ctmodbus --help` for startup options, including web port and TLS settings.

## Interactive commands

Both UIs offer completion, generated help, and unique command prefixes.
Use `help` for the command list, or `help read` for a specific group.
Enter `client`, `server`, or `proxy` for a short overview with examples.
`help client`, `help server`, and `help proxy` give the full references.

Connect to a device, then read or write its addresses:

```text
client start tcp 10.10.10.1 --port 502 --unit 1
read id
read discrete_inputs 1
read coils 1,3,5,7
read input_registers 5,10-30,90-99
read holding_registers 50-58
read holding_registers 0-500 --max-count 100
write coils 128 0
write coils 76 0,1,1,0,1,0,0,1
write holding_registers 1000 14302,188,305
write holding_registers 100 0x8000,0b0100110,0d800
write holding_registers 100 -- -32768,-1,32767
client status
client stop
```

Replace the host, unit, and addresses with ones your device supports. Only one
client connection can be open at a time. Other connection options include:

```text
client start udp 10.10.10.1 --port 10502
client start tls plc.example.com --ca-file plant-ca.pem
client start rtu /dev/ttyUSB0 --baudrate 9600 --parity E
client start ascii COM2 --baudrate 9600
```

These are alternatives: run `client stop` before changing connections.
`client discover` suggests serial ports and local services. Serial completion
includes USB manufacturer/product details when available. You can still enter
device paths and symlinks that discovery doesn't list. Opening UDP creates a
local socket; it doesn't confirm that a remote device is responding.

### Addresses and raw writes

Addresses are **zero-based wire addresses**, from 0 through 65535. Convert
4xxxx reference numbers to wire addresses before using them. Read ranges include
both ends: `50-58` reads nine addresses. Lists preserve order and repetitions,
with at most 65,536 addresses per read.

`--max-count` limits the addresses in each request, up to 2,000 bits or 125
registers. Larger reads split into requests automatically.

Writes take a starting address and comma-separated values for consecutive
addresses. Coils accept `0` or `1`; holding registers accept -32768–65535.
Each value uses one 16-bit register. Negative values use two's complement:
`-1` writes `0xFFFF`.

Register values accept decimal and `0x`/`0b`/`0o`/`0d` prefixes, signs, and
underscores. Mix prefixes freely: `0x8000,0b0100110,0d800` writes 32768, 38,
and 800. Put `--` before a list starting with a negative value. Leave out spaces
around commas or quote the whole list. Results and records show unsigned wire
values; use [tags](#tags) for floats and values spanning multiple registers.

One value uses a single-write function; multiple values use one multiple-write
request. The limits are 1,968 coils or 123 registers, and writes never split.
A matching acknowledgement confirms the write response, not an independent
readback. Failed or interrupted writes may still have reached the device;
ctmodbus reports an unconfirmed outcome explicitly.

## Connection options and operation results

Client defaults are:

| Setting | Default | Option |
| --- | --- | --- |
| Unit ID | 1, supported range 1–247 | `--unit` |
| Timeout | 3 seconds for network, 1 for serial | `--timeout` |
| Retries | 0, supported range 0–10 | `--retries` |
| Network port | 502 for TCP/UDP, 802 for TLS | `--port` |
| Serial framing | 9600 baud, 8 data bits, no parity, 1 stop bit | `--baudrate`, `--bytesize`, `--parity`, `--stopbits` |

Supply host and port separately, including for IPv6 addresses.

TLS uses Modbus TLS framing and verifies the certificate and hostname by
default. Use `--ca-file PATH` for a private CA, and
`--cert-file PATH --key-file PATH` for client authentication. The certificate
file can include its key; otherwise supply a separate unencrypted key file.
`--insecure` disables server certificate and hostname verification.
Saved configs retain paths and verification settings, so the referenced files
must be available when reconnecting.

Requests run asynchronously and share one serialized connection. The status bar
shows connection state and read progress. `client stop` cancels outstanding
work and closes the connection; reconnect explicitly before more device I/O.
In the interactive UI, Ctrl-C clears the input line. Use `client stop` to stop
an active device command.

Read output includes UTC timestamps and compact address/value summaries.
Registers have integer, hex, and character views. Each character represents
one register's Unicode code point; it isn't a UTF-8 string decoder. If a
chunked read fails, the error output retains values already read.

## Tags

Give addresses names and types so you can work with values directly.
Tags belong to the project and use the active client connection and unit.
A tag's type determines its width; supply only its first address.
Connect the client before the read/write commands below.

```text
tags create pause_sw coil 0 bool
tags create state holding_register 0 uint8
tags create counter holding_register 1 uint16
tags create timer holding_register 2 int32
tags create energy input_register 10 float64 --word-order big
tags list
tags show timer
read tags
read tags pause_sw,state,counter,timer
write tag timer 0d33_000
write tag timer 0x8000_0000
write tag timer -- -2_000_000_000
write tag state 0b0111_0001
write tag pause_sw on
```

`read tags` reads all tags in name order. A comma-separated list selects tags
in your requested order, including duplicates. Each tag is read separately,
with other device commands held until the whole command finishes. On failure
or cancellation, completed rows remain visible and unread tags are reported.
Device values can change between reads.
Cancellation closes the connection; reconnect before continuing.

Rename a tag with `tags rename timer duration`.

### Types and values

`tags create` takes a singular table name: `coil`, `discrete_input`,
`input_register`, or `holding_register`. Coils and discrete inputs use `bool`;
registers use signed/unsigned 8-, 16-, 32-, or 64-bit integers, or `float32` and
`float64`. Only coils and holding registers can be written. Overlapping tags
are allowed, with a warning, for alternative interpretations of the same data.

Boolean input accepts `0`/`1`, `false`/`true`, or `off`/`on`. Integers accept
decimal and `0b`, `0o`, `0d`, or `0x` prefixes, with optional underscores.
Floats accept finite decimal or scientific notation; NaN and infinity are
rejected.

For signed tags, unsigned binary/octal/hex literals represent fixed-width bit
patterns. For an `int32`, `0x8000_0000` means -2147483648 and `0xFFFF_FFFF`
means -1. Decimal input must fit the numeric range. Use `--` before a negative
positional value, as in `write tag timer -- -2000000000`.

### Byte and word order

Register tags default to big-endian bytes within each register and
little-endian words across registers. Set `--byte-order little|big` and
`--word-order little|big` to match your device.

An 8-bit tag still uses a full register. Big byte order selects the low byte;
little byte order selects the high byte. Writes zero the unused byte.
Byte and word order don't apply to Boolean tags.

### Import and export

```text
tags export my_tags
tags import my_tags.toml
tags import my_tags.toml --replace
```

Tag files use versioned TOML. Export adds `.toml` if needed and atomically
replaces the destination. Import validates the whole file and applies all rows
or none. Existing names need confirmation in the terminal/web UI, or
`--replace` in CLI and command files. The exact validated contents are retained
while you confirm; project changes and tag edits are blocked until it finishes.
Both commands offer path completion.

Exports assume sequential use. See the
[concurrency limitations](docs/DECISIONS.md#d12--implementation-discrepancies-and-ctui-proposals)
if you're embedding concurrent tag or project operations.

### Removing tags

Delete one tag with `tags delete NAME`, or every tag with `tags delete --all`.
Stop the server and polling first. Bulk deletion needs Yes/No approval in the
terminal/web UI or `--confirm` in CLI. An empty project needs no confirmation.
A name and `--all` can't be combined.

Saved server rules referencing a tag block deletion. Add
`--remove-server-rules` to delete those entries in the same transaction:

```text
tags delete temperature
tags delete temperature --remove-server-rules --confirm
tags delete --all
tags delete --all --remove-server-rules --confirm
```

These are alternatives; replace `temperature` with an existing tag name.
Rule removal needs approval even for one tag. Other server settings and raw
ranges stay intact. If hooks exist, approval also warns that Python references
may need updating, even when deleting a single unreferenced tag. Companion
scripts aren't changed.

Declining approval changes nothing; a transaction failure rolls back both tags
and server rules. Exported files stay untouched and can be imported again later.

## Polling

Run one poll at a time while keeping the terminal/web UI available:

```text
poll tags
poll tags timer,state,pause_sw --interval 0.1 --count 100
poll raw --holding-registers 0-2,10-11 --coils 0-7 --interval 1 --duration 60
poll status
poll stop
```

These are alternative polls; stop one before starting another. `poll tags`
uses all tags in name order or the supplied comma-separated list. `poll raw`
uses the same inclusive ranges as `read`, with a column per address/range.
Table options, ranges, and repeated targets keep their supplied order.

The default interval is one second. Interval and duration must be positive,
finite seconds; count limits started cycles. With both count and duration,
the first limit reached stops new cycles and the active cycle finishes.
In CLI mode, polling streams results and waits before running the next command.
Use limits in scripts; an unlimited CLI poll runs until interrupted.

The first cycle starts immediately. Later cycles follow a fixed schedule
without adding response time to the interval. Busy or overdue ticks are
skipped, never queued for catch-up. All reads in a cycle share the client
connection, so timing is best effort. `poll status` shows targets, limits,
started/completed cycles, skipped ticks, failed columns, and last cycle duration.

Each started cycle appends a row, including unchanged values:

```text
     # |       timer | state | pause_sw
     1 |       33000 |   113 | True
     2 |         ERR |   114 | False

     # | holding_registers:0-2 | holding_registers:10-11 | coils:0-7
     1 | 0000 0071 80E8        | 000A 00FF               | 10110001
     2 | 0000 0072 ERR         | 000B 0100               | 10110011
```

Tags show decoded values; raw bits use `0`/`1` and raw registers use four-digit
uppercase hex. Columns widen and repeat their header when needed. Float32/64
values use up to 9/17 significant digits. `ERR` marks a failed tag or range;
completed chunks remain visible. Other columns and cycles continue while the
connection is usable. Records retain raw values and errors, and old values
aren't shown as fresh results.

Stop polling before editing tags or switching projects. `poll stop` waits for
the active cycle and leaves the connection open. `client stop`, connection loss,
or application shutdown also stop polling. Cancellation closes the connection;
a poll never moves to a replacement connection automatically.

## Server

Run one server alongside the independent client. In a fresh project, the server
exposes all four tables at addresses 0–65535, initially false/zero:

```text
server start tcp 127.0.0.1 --port 5020
server status
server stop
```

Server TCP/UDP default to loopback port 5020; TLS defaults to loopback port
8020 and requires certificate/key files. RTU/ASCII servers use their own serial
port and respond as devices, not passive taps.

Configure raw ranges or typed tags with static, random, or sequence values,
and add Python hooks for device behavior. Edit the definition with
`server config` commands or import TOML. From a repository checkout, try the
[pump/tank example](examples/device.toml) and its
[companion hooks](examples/device_logic.py):

```text
server config import examples/device.toml
server config validate
server config show
server config export device.toml
server start tcp 127.0.0.1 --port 5020
server stop
```

Stop the server before editing its definition or changing projects. Import
replaces the server definition and merges its tags; conflicting tags need
approval or `--replace`. Python hooks execute as trusted application code,
including during validation.

See the [server guide](docs/SERVER.md) for configuration, hooks, and reset
behavior.

### Server request output

Listeners log incoming requests by default:

```text
2026-10-06T14:32:05.123+00:00 SERVER #42 peer=('127.0.0.1', 53120) unit=1 read holding_registers 10-12
```

Lines include UTC timestamps, endpoint, unit, function/table, and address range.
Write previews show at most 16 values; records retain the full payload.
An arrival line describes an attempt, not a successful response.

Use `--quiet` on any `server start` command to suppress routine lines, or
toggle logging while the listener runs:

```text
server logging off
server logging on
```

Errors remain visible and recording continues. Each server start resets its
logging setting from `--quiet`; the setting isn't saved. Request logs append
to output in terminal, web, and CLI modes.

## Proxy

To bridge transports, connect the client to the upstream device, start a server
for downstream clients, then enable proxying:

```text
client start rtu /dev/ttyUSB0 --baudrate 9600 --retries 0
server start tcp 127.0.0.1 --port 5020
proxy start
proxy status
client status
server status
proxy stop
server stop
client stop
```

Any supported client/server transport combination works. Proxying requires zero
client retries and maps the server unit to the connected client's unit.
`proxy stop` restores local simulation. Upstream errors pass through; connection
failure never silently falls back to simulated values. Stopping either endpoint
while proxying needs confirmation; CLI can supply `--confirm`.

`client status` and `server status` show last observations without issuing new
requests. Read values, write acknowledgements, and uncertain writes stay
separate. These views are runtime-only; saved operation records remain available.
See the [proxy guide](docs/SERVER.md#proxying-and-evidence-views) for full
routing details.

### Proxy request output

Proxying logs forwarding attempts using the same request ID as the
[server arrival line](#server-request-output):

```text
2026-10-06T14:32:05.124+00:00 PROXY  #42 upstream=TCP 192.168.1.20:502 unit=7 read holding_registers 10-12
```

Proxy logging is independent of server logging. Use `proxy start --quiet` to
suppress routine forwarding lines, or toggle them while proxying:

```text
proxy logging off
proxy logging on
```

Errors remain visible and recording continues. Each proxy start resets its
logging setting from `--quiet`; the setting isn't saved.

## Management result popups

In the terminal/web UI, management commands show scrollable result popups.
This includes start/stop, status, discovery, tag management, and config edits.
The action finishes before the popup opens. Dismiss it to submit the next
command; servers, proxying, polling, and request logs keep running meanwhile.
Confirmations appear before actions that need approval.

Read/write results, polling rows, and request logs stay in the main output.
CLI management results are plain text. ctui's built-in commands use their own
result presentation.

## Command-line execution

Use the same commands without opening a UI:

```bash
ctmodbus --help
ctmodbus -c 'client start tcp 127.0.0.1 --port 5020' \
  -c 'read holding_registers 0-9' -c 'client stop'
ctmodbus -f commands.txt
```

Repeat `-c`/`--command` and `-f`/`--file` in the order you want them run.
Quote each complete command at the shell. Files take one command per line;
blank lines and lines beginning with `#` are ignored. Commands run sequentially
and stop at the first error.

A server start returns immediately so later commands can run. After a successful
sequence, CLI stays alive if a server is still running. Ctrl-C shuts down server
and client cleanly. Include `server stop` to finish a temporary-server sequence
normally; errors or an explicit `exit confirm` also shut everything down.

Exit codes are 0 for success, 2 for command/argument/protocol errors, 1 for
unexpected command failures, and 130 for Ctrl-C.

## Projects, profiles, and records

Projects keep configs, tags, command history, and decoded operation records in
ctui's user data directory under `io.controlthings.ctmodbus`. Save a client
profile to reuse connection settings:

```text
project
project configs list
project configs show tcp-local
client config load tcp-local
client config show
client config set --unit 7 --timeout 0.5
client config save lab
client start
read holding_registers 0-9
client stop
project history export commands.txt
project export lab.ctui-project
project create another-lab
project load default
client config load lab
```

This example assumes the default project and a device matching the saved
settings. `tcp-local` and `udp-local` are built-in localhost profiles.
Loading a config selects it without connecting; use `client start` to connect.
`client config show` includes the saved source and any unsaved changes.
Saving replaces the named profile with the selected settings, even while
disconnected.

To select settings from scratch, supply transport and target first:

```text
client config set --transport tcp --target localhost --port 502 --unit 1
client config set --timeout 0.2 --retries 0
client config save lab
client start
client status
client stop
client config load lab
```

Edit settings while the client is stopped. Only supplied fields change, and
invalid edits leave the previous selection intact. Fields include network,
serial, and TLS options. Clear certificate paths with `--clear-ca-file`,
`--clear-cert-file`, and `--clear-key-file`. Use `--insecure false` to restore
verification. Changing transports keeps omitted fields, so clear incompatible
TLS settings in the same edit. Selection survives a client stop and clears
when changing projects.

Stop client, server, and polling before switching or resetting projects.
ctui also provides config JSON and whole-project import/export. Live connections,
tasks, runtime observations, and certificate/hook file contents aren't saved.

Records link attempted requests, decoded responses, and errors to a connection
session; they aren't packet captures. Recording failures are reported separately
from device outcomes so an acknowledged write isn't mistaken for a failed one.
Command history contains successful commands; protocol errors remain in
operation records.

## Development and validation

From a repository checkout:

```bash
uv sync --locked --python 3.11
uv run ctmodbus
```

Development and release checks use published `ctui==1.0.0` from the lockfile.
Run the checks with:

```bash
uv run --python 3.11 python -m unittest discover -s tests -v
uv run black --check src tests
uv run isort --check-only src tests
uv run pylint src/ctmodbus
uv lock --check
git diff --check
uv build
```

Tests use temporary projects, local TCP/UDP/TLS servers, and terminal/web
runtimes. POSIX PTYs cover RTU/ASCII framing; Windows skips those tests.
TLS tests need OpenSSL and skip if it isn't available. Physical serial adapters
still need hardware checks.

For a manual TCP fixture, run:

```bash
uv run python tests/server.py tcp --port 5020
```

It also supports `udp`, `rtu`, and `ascii`; serial fixtures take
`--target DEVICE`. Use the [release checklist](RELEASE_CHECKLIST.md) for the
platform matrix, isolated wheel/sdist checks, and publishing procedure.

Moving from 0.x? See [MIGRATION.md](MIGRATION.md) for the command and storage
changes. [CHANGELOG.md](CHANGELOG.md) covers user-facing changes;
[project status](docs/STATUS.md) tracks current work and validation gaps, and
[decisions](docs/DECISIONS.md) explains architecture and accepted choices.
Device cloning, MITM rules, raw/fuzzy requests, tunneling, and historian
integration remain deferred.

## License

Copyright Justin Searle. Licensed under the GNU General Public License,
version 3 or later. See [LICENSE](LICENSE).
