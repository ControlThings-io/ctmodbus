# Serving and proxying Modbus

`server start` creates one application-owned listener, independent of the single client
opened by `client start`. Configure the server before starting it. The TUI remains
interactive; stopping the server keeps the client connection open. Exiting shuts
both down. Project changes and tag/definition edits require a stopped server.
Definitions are saved per project through ctui configs; live observations, tasks,
values and Python functions are not persisted. Whole-project snapshots include
the definition and tags, but not external Python or certificate files.

## Start and stop

```text
server config import examples/device.toml
server config validate
server start tcp 127.0.0.1 --port 5020
server config show
server status
server stop
```

Other listeners share the same local definition:

```text
server start udp 127.0.0.1 --port 5020
server start tls 127.0.0.1 --port 8020 --cert-file server.pem --key-file server.key
server start rtu /dev/ttyUSB0 --baudrate 9600
server start ascii /dev/ttyUSB0 --baudrate 9600
```

TCP/UDP default to loopback port 5020; TLS defaults to loopback port 8020.
Explicit ports 502/802 work when the operating system permits binding them.
Serial defaults match `client start`: 9600 baud, 8 data bits, no parity, one stop bit.
Serial serving responds as a device, not a passive tap. The client and listener
must use different serial ports. Unit IDs 1–247 are supported, defaulting to 1;
serial traffic for other units (including broadcasts) is ignored.
TLS uses native PyModbus TLS framing. Certificate and unencrypted key files are
required. `--ca-file` additionally requires trusted client certificates.

The shared dispatch path supports CLI command sequences. Every server start
returns immediately. After all commands succeed, CLI stays alive if a listener
remains running:

```bash
uv run --with-editable ../ctui ctmodbus \
  -c "server config import examples/device.toml" \
  -c "server start tcp 127.0.0.1 --port 5020"
```

Ctrl-C stops the listener and client cleanly. Commands following a server start
still run before keepalive. A sequence ending with server stop exits normally;
command errors or explicit exit shut down immediately. The previous
`--foreground` option is removed from every transport and interface.
TUI/WUI starts display their completed startup result in a standard message
popup while the listener and request logs remain active. Management popups
preserve the main output; see [result presentation](../README.md#management-result-popups).

## Address maps and values

Without a definition, all four tables implement protocol addresses 0–65535,
initialized to false or zero. Defaults are sparse: no giant initial value array.
This is permitted by Modbus Application Protocol V1.1b3 sections 4.3/4.4. A
request still obeys per-function quantity limits, and cannot cross address 65535.

Server TOML requires `format = "ctmodbus-server"` and integer `version = 1`.
Tag-only TOML requires `format = "ctmodbus-tags"` and integer `version = 1`.
Missing markers, unsupported versions, unknown top-level/nested fields, and
obsolete `tick_seconds` are rejected with actionable errors. Use
`tick_interval_seconds` for periodic hooks. These unreleased formats have no
legacy migration; update old files explicitly. ctui-owned config fields are
unchanged.

Importing TOML replaces the server definition. Omitted tables are unavailable.
Within a table, `unmapped = "illegal"` makes unlisted addresses return exception
02 (Illegal Data Address); `unmapped = "default"` implements unlisted addresses
with the configured initial `default`. Writes to writable default-backed
addresses are retained for that server run.

```toml
format = "ctmodbus-server"
version = 1
unit = 1
seed = 123

[identity]
vendor = "ControlThings"
product = "Example device"
revision = "1.0"

[tables.coils]
unmapped = "default"
default = false

[tables.holding_registers]
unmapped = "illegal"

[[tables.holding_registers.ranges]]
start = 100
end = 199
mode = "static"
value = 42

[[tables.holding_registers.ranges]]
start = 7
end = 7
mode = "sequence"
values = [10, 20, 30]
advance = "time"
interval_seconds = 0.5
repeat = true

[tags.temperature]
table = "input_registers"
address = 10
type = "float32"
byte_order = "big"
word_order = "little"
mode = "random"
min = 20.0
max = 30.0
```

Raw ranges are inclusive and cannot overlap each other. Tags use the shared
project tag codecs and derive their widths from type; numeric order defaults
are big bytes/little words. Named tag rules overlay raw ranges, which overlay
the table default. Server behavior tags cannot overlap each other. Existing
project tags may still overlap for alternate client-side decoding.

Each tag/raw range has one rule:

- `static`: `value` is the initial scalar. Client writes subsequently change
  writable values. Bits accept false/true or 0/1; raw registers accept 0–65535.
- `random`: inclusive `min`/`max` bounds. Integer/Boolean rules use integer
  samples; floating tags use floating samples. An optional top-level `seed`
  makes fresh server runs and resets reproducible.
- `sequence`: a nonempty `values` list; `advance = "read"` advances once per
  successful request touching the address/tag. `advance = "time"` selects by
  elapsed time since server start and requires positive `interval_seconds`.
  `repeat = true` cycles; false holds the final value. Timed rules share a clock.

Typed dynamic tags generate one complete encoded value per request, including
partial reads. A single response cannot combine halves of different samples.
Separate requests can observe different samples. Failed requests do not advance
read sequences or the random generator. Random/sequence rules continue after
writes; replace the rule with static behavior to stop them.

## Assemble a definition in CTUI

```text
server config clear --confirm
server config unit 1
server config seed 123
server config identity --vendor ControlThings --product "Tank and pump simulator" --revision 1.0
server config table coils --unmapped illegal
server config table discrete_inputs --unmapped illegal
server config table input_registers --unmapped illegal
server config table holding_registers --unmapped illegal

tags create pump_enabled coil 0 bool
tags create pump_running discrete_input 0 bool
tags create tank_level input_register 10 float32
server config set tag pump_enabled false
server config set tag pump_running false
server config set tag tank_level 100.0

server config set holding_registers 100-199 42
server config random holding_registers 7 --min 0 --max 100
server config sequence tag tank_level 100,75,50,25 --advance time --interval 1.0
server config sequence holding_registers 8 10,20,30 --advance read --repeat=false

server hook write examples/device_logic.py on_write
server hook tick examples/device_logic.py on_tick --interval 1.0
server config validate
server config export device.toml
```

`set`, `random`, and `sequence` replace a matching tag/exact raw-range rule.
`server config remove tag NAME` removes a server tag rule without deleting the
project tag. `server config remove TABLE RANGE` removes exact configured raw ranges;
the table fallback still applies. `server hook clear` removes all hooks.
Changing a referenced project tag while stopped requires updating/removing its
server rule before validation/start; running definitions cannot be edited.

`server config import FILE --replace` explicitly approves conflicting project tag
definitions. Otherwise differing definitions require a collision-specific TUI
confirmation. Import retains the exact validated file contents throughout
confirmation, and atomically replaces the configuration and merges its tags.
Unrelated project tags remain. Export includes initial definitions and referenced
tags, not last observed or client-written runtime values.

`server config validate` checks definitions, shared project tags and referenced
hook callables without opening a listener. It does not prove hook behavior or
port availability. `server reset --confirm` restores running local values,
random state and sequence clocks from the initial definition. Reset is disabled
in proxy mode. Reset preserves saved settings and timestamped observations,
including earlier proxy evidence. Raw evidence and initial values remain distinct.

## Optional Python hooks

The [pump example](../examples/device.toml) references a companion
[Python module](../examples/device_logic.py):

```toml
[hooks]
module = "device_logic.py"
on_read = "on_read"
on_write = "on_write"
on_tick = "on_tick"
tick_interval_seconds = 1.0
```

All hooks are optional and share one Python file. The module path resolves
relative to the imported TOML file. Export writes a path relative to its
new destination; it does not copy the Python file. Interface hook paths resolve
relative to the current working directory. Hook modules are trusted application
code and execute during validation/loading; this is not a Python sandbox.

Supported signatures:

```python
def on_read(device, tag_names):
    # Once per local read, including partial tags. Return value is ignored.
    device.set("temperature_f", device.get("temperature_c") * 1.8 + 32)

def on_write(device, tag_name, value):
    # After applying a complete tag write, before acknowledging it.
    if tag_name == "pump_enabled":
        device.set("pump_running", bool(value))

def on_tick(device, elapsed_seconds):
    if device.get("pump_running"):
        level = device.get("tank_level")
        device.set("tank_level", max(0.0, level - elapsed_seconds))
```

Functions may be synchronous or async. Keep synchronous functions short; an
async hook has a three-second execution bound. `get` returns a decoded local
tag; `set` checks the scalar type and writes the complete tag without recursively
triggering hooks. Hooks can update locally simulated input tables even though
Modbus clients cannot write them. Full raw writes covering a named tag invoke
`on_write`; partial tag writes are recorded as partial and do not invoke a
complete-value hook.

Request hooks run with pending changes under the local operation lock. A hook
failure rolls back its value, sequence and random-state changes, returns
exception 04 (Server Device Failure), and appears in `server status` and operation
records. Failed ticks leave values unchanged and later ticks continue. Local
hooks and rules are bypassed in proxy mode. Derived-expression syntax and MITM
rule files are not implemented.

## Proxying and evidence views

```text
client start rtu /dev/ttyUSB0 --baudrate 9600 --retries 0
server start tcp 127.0.0.1 --port 5020
proxy start
proxy status
client status
server status
proxy stop
server stop
```

Proxying requires both endpoints. `client stop` and `server stop` warn and
ask for confirmation while the proxy is running; declining preserves both
components. Approval stops proxy routing as part of stopping that component.
CLI can approve explicitly with `--confirm`. The other component stays running.
Unexpected upstream loss still produces a gateway error while proxy mode remains
active; it never silently falls back to local simulation.

Proxying requires both endpoints. The server's configured unit routes to the
client connection's configured unit. One upstream connection is shared by proxy
traffic and console operations; complete exchanges are serialized. Downstream
transaction IDs are preserved, while PyModbus frames the upstream transport.
Local address-map restrictions do not filter proxy requests. The existing
four read tables, single/multiple coil/register writes, and device identification
are supported. Other functions return exception 01 (Illegal Function).

Upstream exceptions pass through. Unavailable/timed-out upstream exchanges
return gateway exception 0B; there is no simulated fallback or automatic retry
of uncertain writes. Proxy start requires `--retries 0`. Confirmed `client stop`
cancels/drains active exchanges and stops proxy routing. Unexpected connection
loss retains proxy mode until `proxy stop` or a confirmed component stop. Obvious loops back to the listener are
rejected. Proxy stop routes new requests locally; already-routed exchanges
finish using their original mode. Saved emulator configuration is preserved.

`client status` works without a server, accumulating successful console
reads and attempted/acknowledged/uncertain writes. It includes the last observed
device identification. `server config show` shows saved initial rules;
`server status` shows current local static tags and last downstream observations. Proxy upstream values are
recorded before the response extension point; downstream values afterwards.
The two views are independent. Neither status command issues network requests.

Unknown addresses remain unknown. Read/write times are UTC. Acknowledgement
is separate from readback; the view labels whether a later read matches or
differs from the last write. Complete typed values require one coherent read;
partial/separate observations are labelled explicitly. State is runtime-only,
cleared on a fresh connection/server run and project change, but durable decoded
operation records remain. Future MITM rules will use a separate TOML file;
only request/response extension seams exist today.

## Request display controls

Listeners default to appending request-arrival lines; proxy mode additionally
appends forwarding lines with the same request ID. `--quiet` on any `server start`
transport suppresses routine server lines. `proxy start --quiet` independently
suppresses routine forwarding lines. `server logging on/off` and
`proxy logging on/off` update these policies live, and status commands show them.
Errors bypass both quiet settings; operation recording is independent of display.
Request IDs increase across listener restarts within an application, and verbosity
settings are runtime-only. See the [usage examples](../README.md#server-and-proxy-request-output)
for timestamps, compact previews, and CLI behavior.
