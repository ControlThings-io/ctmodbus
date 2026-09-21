"""Application ownership and ctui lifecycle integration."""

import asyncio
import shlex
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from ctui import (
    Argument,
    CommandError,
    CommandResult,
    ConfirmationRequired,
    CtuiApp,
    command,
)

from ctmodbus.connection import Connection, ConnectionSettings, create_client
from ctmodbus.discovery import complete_serial, suggestions
from ctmodbus.operations import ModbusCommandMixin
from ctmodbus.tags import TagCommandMixin, TagStore, parse_tag_document

NETWORK_ARGUMENTS = {
    name: Argument(flags=(f"--{name}",))
    for name in ("port", "unit", "timeout", "retries")
}
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
SERIAL_ARGUMENTS["device"] = Argument(completer=complete_serial)


async def complete_profiles(context):
    """Complete saved profile names from the active project."""
    return list(await context.app.configs.list())


class ModbusApp(TagCommandMixin, ModbusCommandMixin, CtuiApp):
    """A Modbus client with one connection and project-scoped services."""

    name = "ctmodbus"
    version = version("ctmodbus")
    description = "An asynchronous Modbus tool for device testing"
    prompt = "ctmodbus> "
    app_id = "io.controlthings.ctmodbus"
    project_schema_version = 2
    project_migrations = {1: (TagStore.CREATE,)}

    def __init__(self, *, client_factory=create_client, **kwargs):
        super().__init__(**kwargs)
        self.connection = Connection(client_factory)
        self.tags = TagStore(self.backend)
        self.statusbar = self.connection_status
        self._device_dispatches = set()
        self._project_changing = False
        self._closing = False
        self._opening = False
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
        """Describe project, transport state, and active read progress."""
        settings = self.connection.settings
        state = (
            f"{settings.label} "
            f"({'connected' if self.connection.connected else 'disconnected'})"
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
        """Refresh the TUI footer without affecting CLI output."""
        self._progress = f" | Read {completed}/{total}" if total else ""
        if hasattr(self, "app"):
            self.app.invalidate()

    async def prepare_tag_import(self, text, tokens, kwargs):
        """Prompt for project-specific tag collisions and return command text."""
        if len(tokens) < 3 or tokens[:2] != ["import", "tags"]:
            return text, None
        path_token = next(
            (token for token in tokens[2:] if not token.startswith("-")), None
        )
        if path_token is None or "--replace" in tokens:
            return text, None
        imported = parse_tag_document(Path(path_token).expanduser())
        collisions = sorted({tag.name for tag in imported} & await self.tags.names())
        if not collisions:
            return text, None
        message = (
            "Tags already exist: "
            + ", ".join(collisions)
            + ". Overwrite them? Re-run with --replace to overwrite without "
            "prompting."
        )
        callback = kwargs.get("confirm_callback")
        if callback is None:
            raise ConfirmationRequired(message)
        approved = callback(message)
        if asyncio.iscoroutine(approved):
            approved = await approved
        return (
            (text + " --replace", None)
            if approved
            else (text, CommandResult.rejected())
        )

    # Lifecycle arbitration is intentionally centralized around command dispatch.
    async def dispatch(  # pylint: disable=too-many-branches,too-many-statements
        self, text, **kwargs
    ):
        tokens = shlex.split(text)
        # Collision names require reading both the file and active project.
        text, rejected = await self.prepare_tag_import(text, tokens, kwargs)
        if rejected is not None:
            return rejected

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
                    "Close the connection and finish device work "
                    "before changing or resetting projects"
                )
            self._project_changing = True
        elif self._project_changing:
            raise CommandError(
                "A project transition is in progress; retry when it finishes"
            )
        opening = item.name in {
            "connect tcp",
            "connect tls",
            "connect udp",
            "connect rtu",
            "connect ascii",
            "profile connect",
        }
        if device_command:
            if self._opening:
                raise CommandError("Connection is opening; retry when it finishes")
            if opening:
                self._opening = True
            if self._closing:
                self._opening = False
                raise CommandError("Connection is closing; retry when it finishes")
            self._device_dispatches.add(task)
        try:
            if project_change:
                # External task cancellation can leave an ended transport's
                # recording session open; finish it in its original project.
                await self.finish_record_session()
            result = await super().dispatch(text, **kwargs)
            if item.name == "project reset" and "all" in tokens and result.accepted:
                await self.tags.clear()
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
        except CommandError as error:
            warnings = self._record_warnings.get(task)
            if warnings:
                raise CommandError(
                    f"{error}\nRecording warning: " + "; ".join(dict.fromkeys(warnings))
                ) from error
            raise
        finally:
            if project_change:
                self._project_changing = False
            if device_command:
                self._device_dispatches.discard(task)
            if opening:
                self._opening = False
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
        except Exception as error:  # pylint: disable=broad-exception-caught
            # A storage failure must not convert an acknowledged write into a
            # reported protocol failure, nor cause the caller to retry a write.
            self._record_warnings.setdefault(asyncio.current_task(), []).append(
                str(error)
            )

    async def finish_record_session(self):
        """End recording before switching connections or closing project storage."""
        session, self._record_session = self._record_session, None
        end_session = getattr(self.records, "end_session", None)
        if session is not None and end_session is not None:
            await end_session(session)

    async def close_connection(self):
        """Drain device commands before transport and record-session cleanup."""
        async with self._close_lock:
            self._closing = True
            try:
                pending = self._device_dispatches - {asyncio.current_task()}
                for task in pending:
                    task.cancel()
                try:
                    if pending:
                        await asyncio.wait_for(
                            asyncio.gather(*pending, return_exceptions=True), timeout=5
                        )
                finally:
                    self.connection.abort()
                    await self.finish_record_session()
            finally:
                self._closing = False
                self.update_progress(0, 0)

    async def on_start(self):
        """Allow a fresh runtime to use this application instance."""
        self._stopping = False

    async def on_stop(self):
        self._stopping = True
        await self.close_connection()

    @command(name="connect")
    async def connect_suggestions(self):
        """List local serial devices and listening services."""
        return await asyncio.to_thread(suggestions)

    async def open_connection(self, settings):
        """Open a transport and its project recording session together."""
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

    @command(name="connect tls", arguments=TLS_ARGUMENTS)
    async def connect_tls(
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
