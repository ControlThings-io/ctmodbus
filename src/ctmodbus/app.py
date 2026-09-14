"""Application ownership and ctui lifecycle integration."""

import asyncio
from dataclasses import replace
from importlib.metadata import version
from typing import Literal

from ctui import Argument, CommandError, CommandResult, CtuiApp, command

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


async def complete_profiles(context):
    return list(await context.app.configs.list())


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
        self._device_dispatches = set()
        self._project_changing = False
        self._closing = False
        self._stopping = False
        self._close_lock = asyncio.Lock()
        self._record_session = None
        self._record_warnings = {}
        self._progress = ""
        self.on("modbus_progress", self.update_progress)
        self.configs.register_template(
            "tcp-local", ConnectionSettings("tcp", "127.0.0.1").as_dict()
        )
        self.configs.register_template(
            "udp-local", ConnectionSettings("udp", "127.0.0.1").as_dict()
        )

    def connection_status(self):
        settings = self.connection.settings
        state = (
            f"{settings.label} ({'connected' if self.connection.connected else 'disconnected'})"
            if settings
            else "Disconnected"
        )
        project = (
            self.backend.current.name
            if self.backend and self.backend.current
            else "unopened"
        )
        return f"Project: {project} | {state}{self._progress}"

    def update_progress(self, completed, total):
        self._progress = f" | Read {completed}/{total}" if total else ""
        if hasattr(self, "app"):
            self.app.invalidate()

    async def dispatch(self, text, **kwargs):
        # Reserve project transitions before the first await. This also covers
        # unique command prefixes, which are resolved to their canonical names.
        item, _ = self.commands.resolve(text)
        project_change = item.name in {
            "project create",
            "project load",
            "project saveas",
            "project import",
            "project reset",
        }
        device_command = item.name.startswith(
            ("connect ", "read ", "write ", "profile ")
        )
        task = asyncio.current_task()
        if self._stopping:
            raise CommandError("Application is stopping")
        if project_change:
            if (
                self._project_changing
                or self._device_dispatches
                or self.connection.client is not None
                or self._closing
            ):
                raise CommandError(
                    "Close the connection and finish device work before changing or resetting projects"
                )
            self._project_changing = True
        elif self._project_changing:
            raise CommandError(
                "A project transition is in progress; retry when it finishes"
            )
        if device_command:
            if self._closing:
                raise CommandError("Connection is closing; retry when it finishes")
            self._device_dispatches.add(task)
        try:
            result = await super().dispatch(text, **kwargs)
            warnings = self._record_warnings.get(task)
            if warnings:
                result = replace(
                    result,
                    output=(result.output or "")
                    + "\nRecording warning: "
                    + "; ".join(dict.fromkeys(warnings)),
                )
            return result
        except asyncio.CancelledError as error:
            raise CommandError("Command cancelled before completion") from error
        finally:
            if project_change:
                self._project_changing = False
            if device_command:
                self._device_dispatches.discard(task)
            self._record_warnings.pop(task, None)

    async def record_operation(self, direction, decoded):
        if self._record_session is None:
            return
        try:
            await self.records.append(
                direction=direction,
                protocol="modbus",
                session=self._record_session,
                decoded=decoded,
            )
        except Exception as error:
            # A storage failure must not convert an acknowledged write into a
            # reported protocol failure, nor cause the caller to retry a write.
            self._record_warnings.setdefault(asyncio.current_task(), []).append(
                str(error)
            )

    async def finish_record_session(self):
        session, self._record_session = self._record_session, None
        end_session = getattr(self.records, "end_session", None)
        if session is not None and end_session is not None:
            await end_session(session)

    async def close_connection(self):
        async with self._close_lock:
            self._closing = True
            try:
                pending = self._device_dispatches - {asyncio.current_task()}
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                await self.connection.close()
                await self.finish_record_session()
            finally:
                self._closing = False
                self.update_progress(0, 0)

    async def on_stop(self):
        self._stopping = True
        await self.close_connection()

    @command(name="connect")
    async def connect_suggestions(self):
        """List local serial devices and listening services."""
        return await asyncio.to_thread(suggestions)

    async def open_connection(self, settings):
        await self.connection.connect(settings)
        try:
            await self.finish_record_session()
            self._record_session = await self.records.start_session(
                "modbus", metadata=settings.as_dict()
            )
        except BaseException:
            self.connection.abort()
            raise
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
        await self.close_connection()
        return CommandResult.append("Session CLOSED")

    @command
    async def cancel(self):
        """Cancel device work and close the connection to discard pending replies."""
        await self.close_connection()
        return CommandResult.append("Device work cancelled; session CLOSED")

    @command(name="profile save")
    async def profile_save(self, name: str):
        """Save the current connection settings as a named project config."""
        if self.connection.settings is None:
            raise CommandError("Connect before saving a profile")
        await self.configs.save(name, self.connection.settings.as_dict())
        return CommandResult.append(f"Saved connection profile {name!r}")

    @command(
        name="profile connect",
        arguments={"name": Argument(completer=complete_profiles)},
    )
    async def profile_connect(self, name: str):
        """Connect using a named project config."""
        values = await self.configs.get(name)
        try:
            settings = ConnectionSettings(**values)
        except (TypeError, ValueError) as error:
            raise CommandError(
                f"Invalid connection profile {name!r}: {error}"
            ) from error
        return await self.open_connection(settings)
