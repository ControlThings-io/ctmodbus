"""Client commands and selected project configuration, independent of live I/O."""

import asyncio
import json
from typing import Literal

from ctui import Argument, CommandError, CommandResult, CompletionItem, command

from ctmodbus.connection import ConnectionSettings
from ctmodbus.data_state import DataState
from ctmodbus.discovery import complete_serial, suggestions
from ctmodbus.server_config import CONFIG_NAME

NETWORK_ARGUMENTS = {
    name: Argument(flags=(f"--{name}",))
    for name in ("port", "unit", "timeout", "retries")
}
NETWORK_ARGUMENTS["host"] = Argument(help="Device hostname or IP address")
TLS_ARGUMENTS = {
    **NETWORK_ARGUMENTS,
    **{
        name: Argument(flags=(f"--{name.replace('_', '-')}",))
        for name in ("ca_file", "cert_file", "key_file", "insecure")
    },
}
SERIAL_ARGUMENTS = {
    name: Argument(flags=(f"--{name}",))
    for name in (
        "unit",
        "timeout",
        "retries",
        "baudrate",
        "bytesize",
        "parity",
        "stopbits",
    )
}
SERIAL_ARGUMENTS["device"] = Argument(
    help="Serial device path", completer=complete_serial
)


CONFIG_ARGUMENTS = {
    name: Argument(flags=("--" + name.replace("_", "-"),))
    for name in (
        "transport",
        "target",
        "port",
        "unit",
        "timeout",
        "retries",
        "baudrate",
        "bytesize",
        "parity",
        "stopbits",
        "ca_file",
        "cert_file",
        "key_file",
        "insecure",
        "clear_ca_file",
        "clear_cert_file",
        "clear_key_file",
    )
}
CONFIG_ARGUMENTS["transport"] = Argument(
    flags=("--transport",),
    choices={
        "tcp": "TCP",
        "udp": "UDP",
        "tls": "Verified TLS",
        "rtu": "Serial RTU",
        "ascii": "Serial ASCII",
    },
)
CONFIG_ARGUMENTS["parity"] = Argument(
    flags=("--parity",), choices={"N": "None", "E": "Even", "O": "Odd"}
)
CONFIG_ARGUMENTS["insecure"] = Argument(
    flags=("--insecure",),
    completer=lambda context: [
        CompletionItem("true", "Disable verification"),
        CompletionItem("false", "Verify TLS certificates"),
    ],
)


async def complete_profiles(context):
    """Complete saved profile names from the active project."""
    return [name for name in await context.app.configs.list() if name != CONFIG_NAME]


class ClientCommandMixin:
    """Client lifecycle and configuration commands sharing application guards."""

    @command(name="client discover")
    async def client_discover(self):
        """List local serial devices and listening services."""
        return await asyncio.to_thread(suggestions)

    async def open_connection(self, settings):
        """Return an appended OPENED result after connection and recording start.

        Connection errors propagate as CommandError. If session setup fails or
        is cancelled, abort the new connection and propagate the exception so
        subsequent operations cannot run without their intended session.
        """
        if (
            self.server.listener
            and settings.transport in ("rtu", "ascii")
            and self.server.serial_device == settings.target
        ):
            raise CommandError("Client and server cannot share the same serial port")
        if self.connection.client is not None:
            raise CommandError("Stop the client before starting another connection")
        if settings != self.selected_client_settings:
            self.client_config_source = None
            self.client_config_saved = None
        self.selected_client_settings = settings
        await self.connection.connect(settings)
        self.client_state = DataState(settings.label)
        try:
            await self.finish_record_session()
            self._record_session = await self.records.start_session(
                "modbus", metadata=settings.as_dict()
            )
        except BaseException:
            self.connection.abort()
            raise
        return CommandResult.append(f"Session OPENED: {settings.label}")

    @command(name="client start tcp", arguments=NETWORK_ARGUMENTS)
    async def client_start_tcp(
        self,
        host: str,
        port: int = 502,
        unit: int = 1,
        timeout: float = 3,
        retries: int = 0,
    ):
        """Open a Modbus TCP session."""
        return await self.open_connection(
            ConnectionSettings(
                "tcp", host, port=port, unit=unit, timeout=timeout, retries=retries
            )
        )

    @command(name="client start tls", arguments=TLS_ARGUMENTS)
    async def client_start_tls(
        self,
        host: str,
        port: int = 802,
        unit: int = 1,
        timeout: float = 3,
        retries: int = 0,
        ca_file: str | None = None,
        cert_file: str | None = None,
        key_file: str | None = None,
        insecure: bool = False,
    ):
        """Open Modbus TLS; verify the server unless --insecure is specified."""
        return await self.open_connection(
            ConnectionSettings(
                "tls",
                host,
                port=port,
                unit=unit,
                timeout=timeout,
                retries=retries,
                ca_file=ca_file,
                cert_file=cert_file,
                key_file=key_file,
                insecure=insecure,
            )
        )

    @command(name="client start udp", arguments=NETWORK_ARGUMENTS)
    async def client_start_udp(
        self,
        host: str,
        port: int = 502,
        unit: int = 1,
        timeout: float = 3,
        retries: int = 0,
    ):
        """Open a Modbus UDP session (does not verify a remote device)."""
        return await self.open_connection(
            ConnectionSettings(
                "udp", host, port=port, unit=unit, timeout=timeout, retries=retries
            )
        )

    @command(name="client start rtu", arguments=SERIAL_ARGUMENTS)
    async def client_start_rtu(
        self,
        device: str,
        unit: int = 1,
        timeout: float = 1,
        retries: int = 0,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: Literal["N", "E", "O"] = "N",
        stopbits: int = 1,
    ):
        """Open a Modbus RTU serial session."""
        return await self.open_connection(
            ConnectionSettings(
                "rtu",
                device,
                unit=unit,
                timeout=timeout,
                retries=retries,
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
            )
        )

    @command(name="client start ascii", arguments=SERIAL_ARGUMENTS)
    async def client_start_ascii(
        self,
        device: str,
        unit: int = 1,
        timeout: float = 1,
        retries: int = 0,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: Literal["N", "E", "O"] = "N",
        stopbits: int = 1,
    ):
        """Open a Modbus ASCII serial session."""
        return await self.open_connection(
            ConnectionSettings(
                "ascii",
                device,
                unit=unit,
                timeout=timeout,
                retries=retries,
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
            )
        )

    @command(name="client start")
    async def client_start(self):
        """Start the selected configuration; loading or editing never opens I/O."""
        if self.selected_client_settings is None:
            raise CommandError("Select settings with client config load or set first")
        return await self.open_connection(self.selected_client_settings)

    @command(name="client stop", arguments={"confirm": Argument(flags=("--confirm",))})
    async def client_stop(
        self, confirm: bool = False
    ):  # pylint: disable=unused-argument
        """Cancel device work and close; dispatch confirms active proxy stops."""
        await self.close_connection()
        return CommandResult.append("Session CLOSED")

    @command(name="client status")
    async def client_status(self):
        """Show connection state and retained read/write evidence without device I/O."""
        heading = (
            f"Connected: {self.connection.settings.label}"
            if self.connection.connected
            else "Disconnected; last session evidence retained"
        )
        return heading + "\n" + self.client_state.show(await self.tags.list())

    def require_stopped_client(self):
        """Reject configuration changes while a live client exists."""
        if self.connection.client is not None:
            raise CommandError("Stop the client before changing its configuration")

    @command(name="client config show")
    def client_config_show(self):
        """Show selected settings, their saved source, and unsaved changes."""
        if self.selected_client_settings is None:
            return "No client configuration selected."
        values = self.selected_client_settings.as_dict()
        dirty = values != self.client_config_saved
        return (
            f"Source: {self.client_config_source or 'command settings'}\n"
            f"Unsaved changes: {'yes' if dirty else 'no'}\n"
            + json.dumps(values, indent=2)
        )

    @command(
        name="client config save",
        arguments={"name": Argument(help="Saved configuration name")},
    )
    async def client_config_save(self, name: str):
        """Save selected settings, replacing NAME; store certificate paths."""
        if name == CONFIG_NAME:
            raise CommandError("That name is reserved for server configuration")
        if self.selected_client_settings is None:
            raise CommandError("Select client settings before saving a configuration")
        values = self.selected_client_settings.as_dict()
        await self.configs.save(name, values)
        self.client_config_source = name
        self.client_config_saved = values
        return CommandResult.append(f"Saved client configuration {name!r}")

    @command(
        name="client config load",
        arguments={
            "name": Argument(
                help="Saved configuration name", completer=complete_profiles
            )
        },
    )
    async def client_config_load(self, name: str):
        """Select saved settings while stopped; require explicit client start."""
        self.require_stopped_client()
        if name == CONFIG_NAME:
            raise CommandError("That name is reserved for server configuration")
        values = await self.configs.get(name)
        try:
            settings = ConnectionSettings(**values)
        except (TypeError, ValueError, CommandError) as error:
            raise CommandError(
                f"Invalid client configuration {name!r}: {error}"
            ) from error
        self.selected_client_settings = settings
        self.client_config_source = name
        self.client_config_saved = settings.as_dict()
        return f"Loaded client configuration {name!r}. Use client start to connect."

    @command(name="client config set", arguments=CONFIG_ARGUMENTS)
    def client_config_set(
        self,
        transport: Literal["tcp", "udp", "tls", "rtu", "ascii"] | None = None,
        target: str | None = None,
        port: int | None = None,
        unit: int | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        baudrate: int | None = None,
        bytesize: int | None = None,
        parity: Literal["N", "E", "O"] | None = None,
        stopbits: int | None = None,
        ca_file: str | None = None,
        cert_file: str | None = None,
        key_file: str | None = None,
        insecure: bool | None = None,
        clear_ca_file: bool = False,
        clear_cert_file: bool = False,
        clear_key_file: bool = False,
    ):
        """Atomically validate supplied fields against stopped selected settings.

        First selection requires --transport and --target. Omitted fields retain
        their values. Clear TLS paths explicitly; --insecure false restores
        verification. Switching transport retains other fields, so clear any
        incompatible TLS options in the same command.
        """
        self.require_stopped_client()
        values = (
            self.selected_client_settings.as_dict()
            if self.selected_client_settings
            else {}
        )
        supplied = {
            "transport": transport,
            "target": target,
            "port": port,
            "unit": unit,
            "timeout": timeout,
            "retries": retries,
            "baudrate": baudrate,
            "bytesize": bytesize,
            "parity": parity,
            "stopbits": stopbits,
            "ca_file": ca_file,
            "cert_file": cert_file,
            "key_file": key_file,
            "insecure": insecure,
        }
        updates = {name: value for name, value in supplied.items() if value is not None}
        if not values and (transport is None or target is None):
            raise CommandError("First selection requires --transport and --target")
        if not values:
            updates.setdefault("port", 802 if transport == "tls" else 502)
            updates.setdefault("timeout", 1 if transport in ("rtu", "ascii") else 3)
        for name, clear in (
            ("ca_file", clear_ca_file),
            ("cert_file", clear_cert_file),
            ("key_file", clear_key_file),
        ):
            if clear:
                if name in updates:
                    raise CommandError(f"Cannot set and clear {name} together")
                updates[name] = None
        settings = ConnectionSettings(**{**values, **updates})
        self.selected_client_settings = settings
        return "Client configuration updated. Use client start to connect."
