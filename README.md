# ControlThings Modbus

An asynchronous Modbus tool for device testing, built with
[ctui](https://github.com/ControlThings-io/ctui) and
[PyModbus](https://github.com/pymodbus-dev/pymodbus).

The 1.0 release candidate supports TCP, UDP, TLS, serial RTU, and serial ASCII;
device identification; coils, discrete inputs, input registers, and holding
registers; and single/multiple coil and holding-register writes.
Project-scoped tags add names and integer, floating-point, or Boolean types to
those wire addresses.

## Installation

Requires Python 3.11 or newer. Install the release candidate from this checkout:

```bash
uv tool install .
```

For development:

```bash
uv sync --locked
uv pip install --python .venv/bin/python --editable ../ctui
uv run --with-editable ../ctui ctmodbus
```

Until release preparation, use the adjacent `../ctui` development checkout.
The editable install makes it available to IDEs using `.venv/bin/python`;
repeat that install after `uv sync`, which can restore the locked package.
Keep `--with-editable ../ctui` on development `uv run` commands. This temporary
setup leaves the declared dependency and lockfile unchanged; release validation
must use the intended published ctui version without the override.

After a release candidate has been published, install it with
`uv tool install 'ctmodbus==1.0.0rc1'` or
`python -m pip install 'ctmodbus==1.0.0rc1'`.

## Interactive commands

Run `ctmodbus` without arguments to open the terminal interface. Commands have
automatic completion, generated help, and unique-prefix matching. Use `help`
for the full list, including ctui's project, config, and history commands.

Larger commands follow **component → action → transport or target**:
`client start tcp HOST`, `server start tcp HOST`, and `proxy start`.
Bare `client`, `server`, and `proxy` open example help in TUI/WUI popups
and print examples in CLI. `help client`, `help server`, and `help proxy` remain generated references. Old connect/serve/profile/close/cancel
spellings and proxy enable/disable are removed; ordinary unique prefixes remain.

```text
client discover                                   # suggest serial ports and local services
client start tcp 10.10.10.1 --port 502 --unit 1
client start udp 10.10.10.1 --port 10502
client start tls plc.example.com --ca-file plant-ca.pem
client start rtu /dev/ttyUSB0 --baudrate 9600 --parity E
client start ascii COM2 --baudrate 9600
read id
read discrete_inputs 1
read coils 1,3,5,7
read input_registers 5,10-30,90-99
read holding_registers 50-58
read holding_registers 0-500 --max-count 100
write coils 128 0
write coils 76 0,1,1,0,1,0,0,1
write holding_registers 1000 14302,188,305
client stop
```

These examples show alternative connections: close the current session before
opening another. Serial-device completion shows the USB manufacturer and product
beside each device path when the operating system provides them. Discovery is
advisory; device paths and symlinks can be supplied even if enumeration does not
list them. UDP opening establishes a local socket and does not prove that a
remote Modbus device is present.

Addresses are **zero-based wire addresses**, from 0 through 65535, rather than
4xxxx reference numbers. Ranges are inclusive and preserve input order and
repetitions. A read accepts at most 65,536 addresses including repetitions.
`--max-count` limits each request, not the total number of addresses: up to
2,000 for bits and 125 for registers. Use `50-58` to read nine addresses at 50.

Writes accept comma-separated integers: 0/1 for coils and 0–65535 for registers.
One value selects a single write; multiple values select one multiple-write
request (at most 1,968 coils or 123 registers). Writes never split automatically.
Success means the device returned a matching acknowledgement, not an independent
readback. Failed or interrupted writes may have reached the device; an
unconfirmed outcome is reported explicitly.

## Tags

Tags give device addresses project-scoped names and types. The type determines
the number of addresses, so creation takes only the first zero-based address.
Tags use the active connection and unit; they do not store a host, unit, or
connection profile.

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
tags rename timer duration
tags delete duration
tags export my_tags
tags import my_tags.toml
```

Types are `bool`, signed and unsigned 8-, 16-, 32-, and 64-bit integers, and
32- or 64-bit floating point. Integer input accepts signed decimal values and
`0b`, `0o`, `0d`, or `0x` radix prefixes; underscores are allowed. Boolean input
accepts `0`/`1`, `false`/`true`, and `off`/`on`. Floating input accepts finite
decimal or scientific notation; NaN and infinity are rejected.

For signed integer tags, unsigned binary, octal, or hexadecimal literals are
interpreted as fixed-width bit patterns: `0x8000_0000` is `-2147483648` for an
`int32`, and `0xFFFF_FFFF` is `-1`. Decimal input remains numeric and must fit
the declared range. Place ctui's `--` end-of-options marker before a negative
positional value, as in `write tag timer -- -2000000000`.

Register tags default to Modbus-standard big-endian byte order inside each
16-bit register and little-endian word order across registers. Override these
with `--byte-order little|big` and `--word-order little|big`. An 8-bit value
occupies the selected byte and the unused byte is written as zero: big byte
order places it in the low byte; little byte order places it in the high byte.
Byte and word order do not apply to Boolean tags.

`tags create` uses the singular table names `coil`, `discrete_input`,
`input_register`, and `holding_register`. Coils and discrete inputs support
`bool`; input and holding registers support numeric types. Writes are limited to
coils and holding registers. Overlapping tags are allowed and reported when
created because alternate interpretations can be useful. Tagged operations
retain normal response validation, recording, cancellation, and uncertain-write
reporting. Multi-tag reads hold one connection reservation across the command,
with one request per tag. Failure or cancellation preserves completed decoded
rows, identifies the failed tag, and reports how many remaining tags were not
read. Cancellation closes the connection; reconnect before further device I/O.
This prevents command interleaving, not changes to device values between reads.

`read tags` without names reads every tag in name order. Supply a comma-separated
list to read only those tags while preserving the requested order and duplicates.

Tag files are versioned TOML. Export appends `.toml` when absent and replaces
the destination atomically. Import validates the whole file before changing the
project. Imports retain the exact validated content during confirmation and
reserve the project and tag edits until finished. The tag merge commits all
rows or none. Both commands suggest filesystem paths in the TUI. Existing names
trigger a TUI confirmation; CLI and command-file use report the conflicting
names and require `--replace`.

Concurrent exports still assume sequential use. See the
[documented concurrency limitations](docs/DECISIONS.md#d12--implementation-discrepancies-and-ctui-proposals)
before embedding concurrent tag-management or project-switching commands.

## Polling

Start one poll in the TUI or WUI; commands remain available while it runs.
`poll tags` snapshots all tags in name order, or takes an ordered comma-separated
list. `poll raw` takes one or more table options using the same inclusive address
syntax as `read`. Each address/range is a separate column; table options and
ranges retain their command-line order, including duplicates.

```text
poll tags
poll tags timer,state,pause_sw --interval 0.1 --count 100
poll raw --holding-registers 0-2,10-11 --coils 0-7 --interval 1 --duration 60
poll status
poll stop
```

The interval defaults to one second. Interval and duration are positive finite
seconds; count is a positive number of started cycles. Both limits work in the
TUI and WUI; when both are supplied, the first reached stops new cycles. Duration
limits cycle starts, allowing an active cycle to finish. In CLI `-c`/`-f` mode,
polling streams output and waits for completion before the next command; supply
limits for scripts. An unlimited CLI poll runs until interrupted.

The first cycle starts immediately. Later cycles target a fixed monotonic-clock
schedule (`start + n × interval`), without adding response time to the interval.
Each cycle serializes all selected reads on the existing connection. Ticks while
that cycle or another device operation is busy are skipped, never queued or
replayed. Event-loop delays also skip obsolete ticks. Scheduling is best effort,
not a guarantee of exact wire timing. `poll status` reports started/completed
cycles, skipped ticks, failed columns, limits, targets, and last cycle duration.

A header and one line per started cycle append to existing output:

```text
     # |       timer | state | pause_sw
     1 |       33000 |   113 | True
     2 |         ERR |   114 | False

     # | holding_registers:0-2 | holding_registers:10-11 | coils:0-7
     1 | 0000 0071 80E8        | 000A 00FF               | 10110001
     2 | 0000 0072 ERR         | 000B 0100               | 10110011
```

Column widths are set when polling starts from headers, tag type bounds, and raw
range lengths. The `#` counter and numeric tags align right; booleans and raw
sequences align left, with ` | ` between every column. Unlimited polls reserve
six counter characters; bounded polls reserve at least three. If any value or
counter outgrows its width, a wider header precedes that row; earlier rows retain
their original spacing. Floats use up to nine significant digits for float32 and
17 for float64, with scientific notation where appropriate and `.0` for integral
values displayed without an exponent. Raw operation records remain unchanged.

Tags display decoded integers, floats, or booleans. Raw bits use contiguous
`0`/`1`; registers use four uppercase hex digits without `0x`, separated by
spaces. A failed tag displays `ERR`; a raw range retains confirmed chunks and
appends `ERR` if a later chunk fails. Other columns and cycles continue while
the connection remains usable. Existing operation records retain confirmed raw
values and detailed errors; previous values are never presented as fresh results.
All completed rows append, including unchanged values.

Tag definitions cannot be edited during polling or target preparation. Stop the
poll before changing projects; polls never follow a replacement connection.
`poll stop` stops future ticks and waits for the active cycle without closing the
connection. `client stop`, connection loss, or application shutdown stop
polling; cancellation closes the transport and requires explicit reconnection.

## Connection options and operation results

All connections accept `--unit` (1–247), `--timeout` (seconds), and `--retries`
(0–10). Defaults are unit 1, zero retries, and a timeout of 3 seconds for network
connections or 1 second for serial connections. Serial defaults are 9600 baud,
8 data bits, no parity, and 1 stop bit; override these with `--baudrate`,
`--bytesize`, `--parity`, and `--stopbits`. TCP/UDP ports default to 502 and TLS to 802; supply
host and port separately, including for IPv6 addresses.

`client start tls HOST` uses Modbus TLS framing and verifies the server certificate
against system trust roots and the supplied hostname. Use `--ca-file PATH` for
a private CA and `--cert-file PATH --key-file PATH` for client authentication.
A certificate file may contain its private key; otherwise supply `--key-file`.
Keys must be unencrypted. Certificate loading runs off the event loop.
`--insecure` explicitly disables server certificate and hostname verification.
Profiles save these file paths and the verification setting, not certificate or
private-key contents; the files must remain available when reconnecting.

Device I/O is asynchronous, with requests serialized on the single connection.
The status bar shows the project, transport state, and read progress. `client stop` cancels outstanding device work and closes the transport. Reconnect
before issuing more requests. The tool does not automatically reconnect.
Ctrl-C clears the input line; use `client stop` to stop running device commands.

Read output includes UTC timestamps and compressed address/value summaries.
Register output includes integer, hex, and character views; the character view
is a Unicode code point per register, not a UTF-8 string decoder. Failed chunked
reads include the completed values in the error output.

## Command-line execution

The same commands work without opening the terminal UI:

```bash
ctmodbus --help
ctmodbus -c 'client start tcp 127.0.0.1 --port 5020' \
  -c 'read holding_registers 0-9' -c 'client stop'
ctmodbus -f commands.txt
```

Repeat `-c`/`--command` and `-f`/`--file` in the desired order. Command files
contain one command per line; blank lines and lines starting with `#` are
ignored. Quote complete commands at the shell. Inline comments in the
interactive examples above are explanatory and should be omitted when typing.

Commands execute sequentially in CLI mode and stop at the first error. Exit
status is 0 for success, 2 for command/argument/protocol errors, and 1 for
unexpected command failures. Shutdown closes the connection automatically.

## Projects, profiles, and records

ctui stores projects in its platform-specific user data directory under the
application ID `io.controlthings.ctmodbus`. Each project contains named configs,
command history, connection recording sessions, and decoded Modbus operation
records. Live connections are never persisted.

```text
project
configs list
configs show tcp-local
client config load tcp-local
client config show
client config set --unit 7 --timeout 0.5
client config save lab
client start
read holding_registers 0-9
client stop
project export lab.ctui-project
history export commands.txt
project create another-lab
project load default
client config load lab
```

`tcp-local` and `udp-local` are built-in localhost profiles. `client config save NAME`
saves selected settings, even while disconnected; `client config load NAME`
validates and selects them without connecting. Use `client start` to connect.
`client config show` displays all selected fields, the source name, and unsaved
changes. `client config set` changes only supplied options, atomically, while
the client is stopped. The first selection requires `--transport` and `--target`:

```text
client config set --transport tcp --target localhost --port 502 --unit 1
client config set --timeout 0.2 --retries 0
client config save lab
client start
client status
client stop
client config load lab
client start
```

Settings include transport, target, port, unit, timeout, retries, serial
baudrate/data bits/parity/stop bits, TLS certificate paths, and insecure mode.
Clear TLS paths with `--clear-ca-file`, `--clear-cert-file`, and
`--clear-key-file`; use `--insecure false` to restore verification or
`--insecure true` to disable it. Edits retain omitted values, including when
changing transport, so clear incompatible TLS fields in the same edit.
File contents, live sockets, polling tasks, and runtime evidence are never
saved in client configs. Selection survives client stop and clears on project
transitions.
ctui also supplies config JSON import/export and whole-project import/export.
Close the connection and finish device work before switching or resetting
projects; this keeps protocol records in the project that initiated them.

Records contain attempted requests, decoded responses, and operation errors,
linked to a session containing connection settings. They are not raw packet
captures. Recording errors are reported separately so an acknowledged write is
not mistaken for a failed write and retried. Command history follows ctui's
successful-command behavior; protocol errors are retained as operation records.

## Development and validation

```bash
uv run --with-editable ../ctui python -m unittest discover -s tests -v
uv run --with-editable ../ctui black --check src tests
uv run --with-editable ../ctui isort --check-only src tests
uv run --with-editable ../ctui pylint src/ctmodbus
uv build
```

Tests use isolated temporary projects, injected clients, actual local TCP/UDP
servers, and a terminal runtime with injected input/output. POSIX systems also
exercise RTU/ASCII over bridged pseudo-terminals; Windows skips those PTY tests.
For a local manual TCP fixture, run
`uv run --with-editable ../ctui python tests/server.py tcp --port 5020`.
The same fixture supports `udp`, `rtu`, and `ascii`; serial fixtures take
`--target DEVICE`. TLS integration tests use temporary certificates generated with `openssl` and
are skipped if that executable is unavailable. Physical serial adapters still
need hardware smoke testing.

This is a breaking migration from 0.x. Legacy command spellings, space-separated
multi-write values, host:port syntax, and old storage formats are not supported.
Polling, device cloning, MITM rules, raw/fuzzy requests,
tunneling, and historian integration remain deferred.

See [MIGRATION.md](MIGRATION.md) for the 0.x transition and
[CHANGELOG.md](CHANGELOG.md) for release-facing changes. Current work and
validation gaps are in [docs/STATUS.md](docs/STATUS.md), architecture and rationale
in [docs/DECISIONS.md](docs/DECISIONS.md), and publication procedures in
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). Local implementation contracts live
in module, class, and callable docstrings.

## License

Copyright Justin Searle. Licensed under the GNU General Public License,
version 3 or later. See [LICENSE](LICENSE).
## Serving and proxying

ctmodbus can serve TCP, UDP, TLS, RTU and ASCII while maintaining an independent
client connection. Configure sparse raw ranges or typed tags with static,
random and sequence behavior, plus optional Python hooks. Server definitions
can be assembled in CTUI or imported/exported as TOML.

```text
server config import examples/device.toml
server start tcp 127.0.0.1 --port 5020
server status
server stop
client start tcp 127.0.0.1 --port 502
client status
```

`proxy start` routes incoming server requests through the connected client;
`proxy stop` restores local behavior. See [server and proxy usage](docs/SERVER.md)
for all commands, foreground CLI serving, hooks, defaults and evidence semantics.

### Server and proxy request output

Server listeners append one line per decoded incoming request by default.
Enabling the proxy adds a forwarding line with the same application-local request
ID. Lines include UTC millisecond timestamps, source, peer or upstream endpoint,
unit, function/table, and address range. Writes show compact bits or four-digit
hex registers, capped at 16 displayed values with an omitted-value count; server
operation records retain the full write payload. Arrival/forwarding lines do not
imply a successful response or write acknowledgement.

```text
server start tcp 127.0.0.1 --port 5020 --quiet
proxy start --quiet
server logging on
proxy logging on
server logging off
proxy logging off
server status
proxy status
```

`--quiet` is available on every `server start` transport and on `proxy start`. Server
arrival and proxy forwarding logging are independent. Live `logging on/off`
commands change routine verbosity without stopping the listener or disabling
records. Starting a listener or enabling the proxy resets its logging policy
from that command's `--quiet` option; settings are runtime-only.

```text
2026-10-06T14:32:05.123+00:00 SERVER #42 peer=('127.0.0.1', 53120) unit=1 read holding_registers 10-12
2026-10-06T14:32:05.124+00:00 PROXY  #42 upstream=TCP 192.168.1.20:502 unit=7 read holding_registers 10-12
```

Request failures remain visible in quiet mode. Failed proxy writes distinguish
potentially unconfirmed outcomes; upstream exceptions are shown without implying
forwarding success. Display escapes control characters. Polling and server logs
share one synchronous append path for terminal, browser, and CLI output. CLI
listeners still need `--foreground` to remain running. Malformed/unsupported
requests that the decoder reports also produce diagnostic lines. Future MITM
logging is not implemented.
