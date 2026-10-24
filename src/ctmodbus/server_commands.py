"""Typed CTUI server-definition, listener, proxy and observation commands.

Project configuration lives in configs, referenced tag definitions in TagStore.
Imports replace server definitions and atomically merge referenced tags after
collision-specific confirmation. Runtime data and hook functions are never saved.
"""

import asyncio
import json
import sqlite3
from contextlib import closing
from dataclasses import replace as replace_settings
from pathlib import Path
from typing import Literal

from ctui import (
    Argument,
    CommandError,
    CommandResult,
    IntegerRanges,
    PathCompleter,
    command,
)

from ctmodbus import server_config
from ctmodbus.connection import ConnectionSettings
from ctmodbus.simulation import Simulator
from ctmodbus.tags import decode_tag_value, encode_tag_value, parse_tag_value

CONFIG_NAME = server_config.CONFIG_NAME
PATH_ARG = {"path": Argument(help="Server TOML file", completer=PathCompleter())}
TARGET_ARGS = {
    "target": Argument(help="Modbus table name or tag"),
    "selection": Argument(help="Tag name or inclusive address ranges"),
}
NETWORK_ARGS = {
    "host": Argument(help="Local bind address"),
    "port": Argument(flags=("--port",)),
    "quiet": Argument(flags=("--quiet",)),
}
SERIAL_ARGS = {
    "device": Argument(help="Local serial device path"),
    **{
        name: Argument(flags=("--" + name.replace("_", "-"),))
        for name in (
            "baudrate",
            "bytesize",
            "parity",
            "stopbits",
            "quiet",
        )
    },
}


class ServerCommandMixin:  # pylint: disable=too-many-public-methods
    """Commands share normal CTUI parsing, dispatch, history and project guards."""

    async def server_definition(self):
        """Load current project definition, defaulting to all-zero full address maps."""
        configs = await self.configs.list()
        return server_config.validate(
            configs.get(CONFIG_NAME, server_config.definition())
        )

    async def save_server_definition(self, config):
        """Validate a candidate before replacing its persistent project definition."""
        config = server_config.validate(config)
        await self.configs.save(CONFIG_NAME, config)

    async def prepare_server_import(self, text, kwargs):
        """Read/confirm once under dispatch guards; keep exact data until
        application.
        """
        item, arguments = self.commands.resolve(text)
        parsed = item.parse_args(arguments)
        config = server_config.load(parsed["path"])
        existing = {tag.name: tag for tag in await self.tags.list()}
        conflicts = [
            name
            for name, values in config["tags"].items()
            if name in existing
            and existing[name] != server_config.tag_from(name, values)
        ]
        if conflicts and not parsed.get("replace", False):
            message = (
                "Server tag definitions differ: "
                + ", ".join(sorted(conflicts))
                + ". Replace them? Use --replace to approve without prompting."
            )
            if not await self.confirm_replacement(message, kwargs):
                return CommandResult.rejected()
        self._prepared_server_imports[asyncio.current_task()] = config
        return None

    @command(
        name="server config import",
        arguments={**PATH_ARG, "replace": Argument(flags=("--replace",))},
    )
    async def server_config_import(self, path: Path, replace: bool = False):
        """Replace server definition and merge its tags after conflict confirmation."""
        config = self._prepared_server_imports.get(asyncio.current_task())
        if config is None:
            config = server_config.load(path)
            existing = {tag.name: tag for tag in await self.tags.list()}
            if not replace and any(
                name in existing
                and existing[name] != server_config.tag_from(name, item)
                for name, item in config["tags"].items()
            ):
                raise CommandError("Existing server tags differ; use --replace")
        await self.tags.ensure()
        cursor = await self.backend.connection.execute("PRAGMA database_list")
        database = next(row[2] for row in await cursor.fetchall() if row[1] == "main")
        tags = [
            server_config.tag_from(name, item) for name, item in config["tags"].items()
        ]
        with closing(sqlite3.connect(database, timeout=0)) as connection:
            with connection:
                connection.executemany(
                    "INSERT OR REPLACE INTO tags VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (t.name, t.table, t.address, t.type, t.byte_order, t.word_order)
                        for t in tags
                    ],
                )
                connection.execute(
                    "INSERT INTO configs(name,value,template) VALUES (?,?,0) "
                    "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    (CONFIG_NAME, json.dumps(config)),
                )
        await self.backend.touch()
        return f"Imported server definition with {len(tags)} tags."

    @command(name="server config export", arguments=PATH_ARG)
    async def server_config_export(self, path: Path):
        """Export definition and referenced tags, not live values or Python source."""
        destination = server_config.export(await self.server_definition(), path)
        return f"Exported server definition to {destination}."

    @command(
        name="server config clear",
        arguments={"confirm": Argument(flags=("--confirm",))},
    )
    async def server_config_clear(self, confirm: bool = False):
        """Replace server configuration with an empty address map; keep project tags."""
        if not confirm:
            raise CommandError("Use --confirm to clear the server definition")
        await self.save_server_definition(server_config.definition(False))
        return (
            "Server definition cleared; no addresses available. Project tags retained."
        )

    @command(
        name="server config unit",
        arguments={"unit": Argument(help="Server unit ID, 1–247")},
    )
    async def server_config_unit(self, unit: int):
        """Set the server unit ID independently of the connected client unit."""
        config = await self.server_definition()
        config["unit"] = unit
        await self.save_server_definition(config)
        return f"Server unit set to {unit}."

    @command(
        name="server config seed",
        arguments={"seed": Argument(help="Reproducible random seed")},
    )
    async def server_config_seed(self, seed: int):
        """Set the random seed used for each new local server run."""
        config = await self.server_definition()
        config["seed"] = seed
        await self.save_server_definition(config)
        return f"Server seed set to {seed}."

    @command(
        name="server config identity",
        arguments={
            name: Argument(flags=("--" + name,))
            for name in ("vendor", "product", "revision")
        },
    )
    async def server_config_identity(
        self,
        vendor: str = "ControlThings",
        product: str = "ctmodbus simulator",
        revision: str = "1.0",
    ):
        """Set the device-identification vendor, product, and revision."""
        config = await self.server_definition()
        config["identity"] = {
            "vendor": vendor,
            "product": product,
            "revision": revision,
        }
        await self.save_server_definition(config)
        return "Server identification updated."

    @command(
        name="server config table",
        arguments={
            "table": Argument(help="Modbus table"),
            "unmapped": Argument(flags=("--unmapped",)),
            "default": Argument(flags=("--default",)),
        },
    )
    async def server_config_table(
        self,
        table: Literal[
            "coils", "discrete_inputs", "input_registers", "holding_registers"
        ],
        unmapped: Literal["illegal", "default"] = "illegal",
        default: str = "0",
    ):
        """Set availability and initial fallback value for unspecified addresses."""
        config = await self.server_definition()
        config["tables"][table].update(
            unmapped=unmapped, default=self.raw_value(default)
        )
        await self.save_server_definition(config)
        return f"{table}: unmapped={unmapped}, default={default}."

    @staticmethod
    def raw_value(text):
        """Parse a Boolean or radix/decimal integer from command input."""
        if text.lower() in ("true", "on", "false", "off"):
            return text.lower() in ("true", "on")
        try:
            return (
                int(text, 0)
                if text.lower().lstrip("+-").startswith(("0x", "0b", "0o"))
                else int(text)
            )
        except ValueError as error:
            raise CommandError(f"Invalid raw value: {text}") from error

    async def set_server_rule(self, target, selection, rule):
        """Replace matching rules, reject ambiguous overlaps, and persist atomically."""
        config = await self.server_definition()
        if target == "tag":
            tag = await self.tags.get(selection)
            item = {**tag.as_dict(), "address": tag.address}
            for key in ("value", "min", "max"):
                if key in rule:
                    rule[key] = parse_tag_value(tag, rule[key])
            if "values" in rule:
                rule["values"] = [
                    parse_tag_value(tag, value) for value in rule["values"]
                ]
            config["tags"][selection] = {**item, **rule}
        else:
            if target not in config["tables"]:
                raise CommandError("Target must be tag or a Modbus table")
            ranges = IntegerRanges(selection)
            if ranges.count > 65536 or any(
                span.start < 0 or span.stop > 65536 for span in ranges
            ):
                raise CommandError("Addresses must fit 0–65535")
            for key in ("value", "min", "max"):
                if key in rule:
                    rule[key] = self.raw_value(rule[key])
            if "values" in rule:
                rule["values"] = [self.raw_value(value) for value in rule["values"]]
            existing = config["tables"][target]["ranges"]
            for span in ranges:
                existing[:] = [
                    r
                    for r in existing
                    if (r["start"], r["end"]) != (span.start, span.stop - 1)
                ]
                existing.append({"start": span.start, "end": span.stop - 1, **rule})
        await self.save_server_definition(config)
        return f"Set {rule['mode']} behavior for {target} {selection}."

    @command(
        name="server config set",
        arguments={**TARGET_ARGS, "value": Argument(help="Initial scalar value")},
    )
    async def server_config_set(self, target: str, selection: str, value: str):
        """Set initial tag or raw range values, replacing matching dynamic rules."""
        return await self.set_server_rule(
            target, selection, {"mode": "static", "value": value}
        )

    @command(
        name="server config random",
        arguments={
            **TARGET_ARGS,
            "minimum": Argument(flags=("--min",)),
            "maximum": Argument(flags=("--max",)),
        },
    )
    async def server_config_random(
        self, target: str, selection: str, minimum: str = "0", maximum: str = "1"
    ):
        """Generate bounded values on each successful read; writes do not disable
        rules.
        """
        return await self.set_server_rule(
            target, selection, {"mode": "random", "min": minimum, "max": maximum}
        )

    @command(
        name="server config sequence",
        arguments={
            **TARGET_ARGS,
            "values": Argument(help="Comma-separated sequence values"),
            "advance": Argument(flags=("--advance",)),
            "interval": Argument(flags=("--interval",)),
            "repeat": Argument(flags=("--repeat",)),
        },
    )
    async def server_config_sequence(
        self,
        target: str,
        selection: str,
        values: list[str],
        advance: Literal["read", "time"] = "read",
        interval: float | None = None,
        repeat: bool = True,
    ):
        """Cycle values on reads or elapsed time; --repeat=false holds the final
        value.
        """
        rule = {
            "mode": "sequence",
            "values": values,
            "advance": advance,
            "repeat": repeat,
        }
        if interval is not None:
            rule["interval_seconds"] = interval
        return await self.set_server_rule(target, selection, rule)

    async def set_server_hook(self, name, module, function, interval=None):
        """Attach a companion function; all hooks share one Python module."""
        config = await self.server_definition()
        path = str(module.expanduser().resolve())
        if config["hooks"].get("module", path) != path:
            raise CommandError(
                "Hooks must share a module; clear hooks before switching modules"
            )
        config["hooks"].update(module=path, **{name: function})
        if interval is not None:
            config["hooks"]["tick_interval_seconds"] = interval
        await self.save_server_definition(config)
        return f"Configured {name}: {function}."

    @command(
        name="server hook read",
        arguments={
            "module": Argument(help="Companion Python file", completer=PathCompleter()),
            "function": Argument(help="Read hook function name"),
        },
    )
    async def server_hook_read(self, module: Path, function: str):
        """Attach on_read(device, tag_names), once per local read request."""
        return await self.set_server_hook("on_read", module, function)

    @command(
        name="server hook write",
        arguments={
            "module": Argument(help="Companion Python file", completer=PathCompleter()),
            "function": Argument(help="Write hook function name"),
        },
    )
    async def server_hook_write(self, module: Path, function: str):
        """Attach on_write(device, tag_name, value) for complete successful tag
        writes.
        """
        return await self.set_server_hook("on_write", module, function)

    @command(
        name="server hook tick",
        arguments={
            "module": Argument(help="Companion Python file", completer=PathCompleter()),
            "function": Argument(help="Tick hook function name"),
            "interval": Argument(flags=("--interval",)),
        },
    )
    async def server_hook_tick(self, module: Path, function: str, interval: float = 1):
        """Attach on_tick(device, elapsed_seconds) for periodic local updates."""
        return await self.set_server_hook("on_tick", module, function, interval)

    @command(name="server hook clear")
    async def server_hook_clear(self):
        """Remove all companion hooks from the stopped server definition."""
        config = await self.server_definition()
        config["hooks"] = {}
        await self.save_server_definition(config)
        return "Server hooks cleared."

    async def validate_server_tags(self, config):
        """Require server tags to match their shared project definitions."""
        existing = {tag.name: tag for tag in await self.tags.list()}
        for name, item in config["tags"].items():
            if existing.get(name) != server_config.tag_from(name, item):
                raise CommandError(
                    f"Server tag {name!r} differs from the project tag; "
                    "remove or reconfigure its rule"
                )

    @command(name="server config remove", arguments=TARGET_ARGS)
    async def server_config_remove(self, target: str, selection: str):
        """Remove a tag rule or raw ranges, retaining tags and table fallback."""
        config = await self.server_definition()
        if target == "tag":
            if selection not in config["tags"]:
                raise CommandError("No server rule exists for that tag")
            del config["tags"][selection]
        elif target in config["tables"]:
            ranges = IntegerRanges(selection)
            requested = {(span.start, span.stop - 1) for span in ranges}
            existing = config["tables"][target]["ranges"]
            if not requested <= {(rule["start"], rule["end"]) for rule in existing}:
                raise CommandError("Remove requires exact configured ranges")
            config["tables"][target]["ranges"] = [
                rule
                for rule in existing
                if (rule["start"], rule["end"]) not in requested
            ]
        else:
            raise CommandError("Target must be tag or a Modbus table")
        await self.save_server_definition(config)
        return "Server rules removed."

    @command(name="server config validate")
    async def server_config_validate(self):
        """Check configuration and trusted hook callables without opening a listener."""
        config = await self.server_definition()
        await self.validate_server_tags(config)
        await asyncio.to_thread(Simulator.load_hooks, config)
        return (
            "Server configuration valid. "
            "Listener binding and hook behavior are not tested."
        )

    @command(name="server config show")
    async def server_config_show(self):
        """Show saved initial values and rules, separate from runtime evidence."""
        return server_config.dumps(await self.server_definition())

    async def show_server_data(self):
        """Show local static tag values and retained downstream evidence without I/O."""
        lines = []
        if self.server.simulator is not None:
            lines.append(
                "Current local static tag values (separate from proxy observations):"
            )
            simulator = self.server.simulator
            for name, tag in simulator.tags.items():
                rule = simulator.config["tags"][name]
                if rule.get("mode", "static") == "static":
                    initial = self.server.simulator.config["tags"][name].get("value", 0)
                    raw = [
                        simulator.values.get((tag.table, tag.address + offset), value)
                        for offset, value in enumerate(encode_tag_value(tag, initial))
                    ]
                    lines.append(f"{name} = {decode_tag_value(tag, raw)!r}")
        lines.append(self.server.state.show(await self.tags.list()))
        return "\n".join(lines)

    async def start_server(self, settings, quiet=False, **tls):
        """Bind the server and return immediately; CLI lifetime belongs to the app."""
        try:
            config = await self.server_definition()
            await self.validate_server_tags(config)
            settings = replace_settings(settings, unit=config["unit"])
            await self.server.start(config, settings, quiet=quiet, **tls)
        except (OSError, ValueError, RuntimeError) as error:
            raise CommandError(f"Server start failed: {error}") from error
        return CommandResult.append(f"Server {self.server.label}")

    @command(name="server start tcp", arguments=NETWORK_ARGS)
    async def server_start_tcp(
        self,
        host: str = "127.0.0.1",
        port: int = 5020,
        quiet: bool = False,
    ):
        """Start a Modbus TCP listener without blocking later commands."""
        return await self.start_server(
            ConnectionSettings("tcp", host, port=port), quiet=quiet
        )

    @command(name="server start udp", arguments=NETWORK_ARGS)
    async def server_start_udp(
        self,
        host: str = "127.0.0.1",
        port: int = 5020,
        quiet: bool = False,
    ):
        """Serve Modbus UDP from the local definition."""
        return await self.start_server(
            ConnectionSettings("udp", host, port=port), quiet=quiet
        )

    @command(
        name="server start tls",
        arguments={
            **NETWORK_ARGS,
            **{
                name: Argument(flags=("--" + name.replace("_", "-"),))
                for name in ("cert_file", "key_file", "ca_file")
            },
        },
    )
    async def server_start_tls(
        self,
        host: str = "127.0.0.1",
        port: int = 8020,
        cert_file: str | None = None,
        key_file: str | None = None,
        ca_file: str | None = None,
        quiet: bool = False,
    ):
        """Serve native Modbus TLS; optional CA roots require client certificates."""
        return await self.start_server(
            ConnectionSettings("tls", host, port=port),
            quiet=quiet,
            cert_file=cert_file,
            key_file=key_file,
            ca_file=ca_file,
        )

    @command(name="server start rtu", arguments=SERIAL_ARGS)
    async def server_start_rtu(
        self,
        device: str,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: Literal["N", "E", "O"] = "N",
        stopbits: int = 1,
        quiet: bool = False,
    ):
        """Respond as an RTU device on a local serial port, not a traffic tap."""
        return await self.start_server(
            ConnectionSettings(
                "rtu",
                device,
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
            ),
            quiet=quiet,
        )

    @command(name="server start ascii", arguments=SERIAL_ARGS)
    async def server_start_ascii(
        self,
        device: str,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: Literal["N", "E", "O"] = "N",
        stopbits: int = 1,
        quiet: bool = False,
    ):
        """Respond as an ASCII device on a local serial port."""
        return await self.start_server(
            ConnectionSettings(
                "ascii",
                device,
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
            ),
            quiet=quiet,
        )

    @command(name="server stop", arguments={"confirm": Argument(flags=("--confirm",))})
    async def server_stop(
        self, confirm: bool = False
    ):  # pylint: disable=unused-argument
        """Stop the listener; dispatch confirms proxy stops; retain the client."""
        await self.server.stop()
        return "Server stopped."

    @command(name="server status")
    async def server_status(self):
        """Show listener, proxy mode and the last hook/transport/storage error."""
        mode = "proxy" if self.server.proxy else "local"
        async with self.server.request_lock:
            data = await self.show_server_data()
        return (
            f"Server: {self.server.label}\nMode: {mode}\n"
            f"Request logging: {'on' if self.server.request_logging else 'off'}\n"
            f"Proxy logging: {'on' if self.server.proxy_logging else 'off'}\n"
            f"Last error: {self.server.last_error or 'none'}\n{data}"
        )

    @command(name="server reset", arguments={"confirm": Argument(flags=("--confirm",))})
    async def server_reset(self, confirm: bool = False):
        """Reset local runtime values, random seed and sequences; leave proxy
        evidence alone. Last observations stay timestamped historical evidence.
        """
        if not confirm:
            raise CommandError("Use --confirm to reset local simulation state")
        if self.server.listener is None or self.server.proxy:
            raise CommandError("Reset requires a running local server")
        async with self.server.request_lock:
            current = self.server.simulator
            self.server.simulator = Simulator(current.config, current.hooks)
        return "Local simulation reset."

    @command(
        name="server logging",
        arguments={
            "state": Argument(help="Enable or disable routine server request lines")
        },
    )
    def server_logging(self, state: Literal["on", "off"]):
        """Change server verbosity; errors remain visible and records unchanged."""
        self.server.request_logging = state == "on"
        return CommandResult.append(f"Server request logging {state}.")
