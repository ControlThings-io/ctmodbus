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
uv run ctmodbus
```

After a release candidate has been published, install it with
`uv tool install 'ctmodbus==1.0.0rc1'` or
`python -m pip install 'ctmodbus==1.0.0rc1'`.

## Interactive commands

Run `ctmodbus` without arguments to open the terminal interface. Commands have
automatic completion, generated help, and unique-prefix matching. Use `help`
for the full list, including ctui's project, config, and history commands.

```text
connect                                           # suggest serial ports and local services
connect tcp 10.10.10.1 --port 502 --unit 1
connect udp 10.10.10.1 --port 10502
connect tls plc.example.com --ca-file plant-ca.pem
connect rtu /dev/ttyUSB0 --baudrate 9600 --parity E
connect ascii COM2 --baudrate 9600
read id
read discrete_inputs 1
read coils 1,3,5,7
read input_registers 5,10-30,90-99
read holding_registers 50-58
read holding_registers 0-500 --max-count 100
write coils 128 0
write coils 76 0,1,1,0,1,0,0,1
write holding_registers 1000 14302,188,305
close
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
tag create pause_sw coil 0 bool
tag create state holding_register 0 uint8
tag create counter holding_register 1 uint16
tag create timer holding_register 2 int32
tag create energy input_register 10 float64 --word-order big
tag list
tag show timer
read tags
read tags pause_sw,state,counter,timer
write tag timer 0d33_000
write tag timer 0x8000_0000
write tag timer -- -2_000_000_000
write tag state 0b0111_0001
write tag pause_sw on
tag rename timer duration
tag delete duration
tag export my_tags
tag import my_tags.toml
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

`tag create` uses the singular table names `coil`, `discrete_input`,
`input_register`, and `holding_register`. Coils and discrete inputs support
`bool`; input and holding registers support numeric types. Writes are limited to
coils and holding registers. Overlapping tags are allowed and reported when
created because alternate interpretations can be useful. Tagged operations
retain normal response validation, recording, cancellation, and uncertain-write
reporting. Multi-tag reads currently issue one request per tag; if a later tag
fails, earlier values remain in operation records but are not included in the
failed command's output.

`read tags` without names reads every tag in name order. Supply a comma-separated
list to read only those tags while preserving the requested order and duplicates.

Tag files are versioned TOML. Export appends `.toml` when absent and replaces
the destination atomically. Import validates the whole file before changing the
project. Both commands suggest filesystem paths in the TUI. Existing names
trigger a TUI confirmation; CLI and command-file use report the conflicting
names and require `--replace`.

Tag imports and exports currently assume sequential use. See the
[documented concurrency limitations](docs/DECISIONS.md#d12--implementation-discrepancies-and-ctui-proposals)
before embedding concurrent tag-management or project-switching commands.

## Connection options and operation results

All connections accept `--unit` (1–247), `--timeout` (seconds), and `--retries`
(0–10). Defaults are unit 1, zero retries, and a timeout of 3 seconds for network
connections or 1 second for serial connections. Serial defaults are 9600 baud,
8 data bits, no parity, and 1 stop bit; override these with `--baudrate`,
`--bytesize`, `--parity`, and `--stopbits`. TCP/UDP ports default to 502 and TLS to 802; supply
host and port separately, including for IPv6 addresses.

`connect tls HOST` uses Modbus TLS framing and verifies the server certificate
against system trust roots and the supplied hostname. Use `--ca-file PATH` for
a private CA and `--cert-file PATH --key-file PATH` for client authentication.
A certificate file may contain its private key; otherwise supply `--key-file`.
Keys must be unencrypted. Certificate loading runs off the event loop.
`--insecure` explicitly disables server certificate and hostname verification.
Profiles save these file paths and the verification setting, not certificate or
private-key contents; the files must remain available when reconnecting.

Device I/O is asynchronous, with requests serialized on the single connection.
The status bar shows the project, transport state, and read progress. `cancel`
or `close` cancels outstanding device work and closes the transport. Reconnect
before issuing more requests. The tool does not automatically reconnect.
Ctrl-C clears the input line; use `cancel` to stop running device commands.

Read output includes UTC timestamps and compressed address/value summaries.
Register output includes integer, hex, and character views; the character view
is a Unicode code point per register, not a UTF-8 string decoder. Failed chunked
reads include the completed values in the error output.

## Command-line execution

The same commands work without opening the terminal UI:

```bash
ctmodbus --help
ctmodbus -c 'connect tcp 127.0.0.1 --port 5020' \
  -c 'read holding_registers 0-9' -c 'close'
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
profile connect tcp-local
profile save lab
read holding_registers 0-9
close
project export lab.ctui-project
history export commands.txt
project create another-lab
project load default
profile connect lab
```

`tcp-local` and `udp-local` are built-in localhost profiles. `profile save NAME`
saves the current settings; `profile connect NAME` validates and loads them.
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
uv run python -m unittest discover -s tests -v
uv run black --check src tests
uv run isort --check-only src tests
uv run pylint src/ctmodbus
uv build
```

Tests use isolated temporary projects, injected clients, actual local TCP/UDP
servers, and a terminal runtime with injected input/output. POSIX systems also
exercise RTU/ASCII over bridged pseudo-terminals; Windows skips those PTY tests.
For a local manual TCP fixture, run `uv run python tests/server.py tcp --port 5020`.
The same fixture supports `udp`, `rtu`, and `ascii`; serial fixtures take
`--target DEVICE`. TLS integration tests use temporary certificates generated with `openssl` and
are skipped if that executable is unavailable. Physical serial adapters still
need hardware smoke testing.

This is a breaking migration from 0.x. Legacy command spellings, space-separated
multi-write values, host:port syntax, and old storage formats are not supported.
Polling, simulation, proxies, raw/fuzzy requests,
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
