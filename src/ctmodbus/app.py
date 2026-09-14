"""Application ownership and ctui lifecycle integration."""

import asyncio
from importlib.metadata import version
from typing import Literal

from ctui import Argument, CommandResult, CtuiApp, command

from ctmodbus.connection import Connection, ConnectionSettings, create_client
from ctmodbus.discovery import complete_serial, suggestions
from ctmodbus.operations import ModbusCommands

NETWORK_ARGUMENTS = {
    name: Argument(flags=(f"--{name}",))
    for name in ("port", "unit", "timeout", "retries")
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
SERIAL_ARGUMENTS["device"] = Argument(completer=complete_serial)


class ModbusApp(ModbusCommands, CtuiApp):
    """A Modbus client with one connection and project-scoped services."""

    name = "ctmodbus"
    version = version("ctmodbus")
    description = "An asynchronous Modbus tool for device testing"
    prompt = "ctmodbus> "
    app_id = "io.controlthings.ctmodbus"

    def __init__(self, *, client_factory=create_client, **kwargs):
        super().__init__(**kwargs)
        self.connection = Connection(client_factory)
        self.statusbar = self.connection_status

    def connection_status(self):
        settings = self.connection.settings
        return (
            f"{settings.label} ({'connected' if self.connection.connected else 'disconnected'})"
            if settings
            else "Disconnected"
        )

    async def on_stop(self):
        await self.connection.close()

    @command(name="connect")
    async def connect_suggestions(self):
        """List local serial devices and listening services."""
        return await asyncio.to_thread(suggestions)

    async def open_connection(self, settings):
        await self.connection.connect(settings)
        return CommandResult.append(f"Session OPENED: {settings.label}")

    @command(name="connect tcp", arguments=NETWORK_ARGUMENTS)
    async def connect_tcp(
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

    @command(name="connect udp", arguments=NETWORK_ARGUMENTS)
    async def connect_udp(
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

    @command(name="connect rtu", arguments=SERIAL_ARGUMENTS)
    async def connect_rtu(
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

    @command(name="connect ascii", arguments=SERIAL_ARGUMENTS)
    async def connect_ascii(
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

    @command
    async def close(self):
        """Close the session and cancel outstanding device operations."""
        await self.connection.close()
        return CommandResult.append("Session CLOSED")
