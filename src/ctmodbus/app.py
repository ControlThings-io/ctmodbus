"""Application ownership, shared TUI/CLI dispatch, and ctui lifecycle integration.

ModbusApp owns the connection, project services, recording session, and command
tasks. Command methods return strings or CommandResult; expected failures use
CommandError. ctui derives usage and completion from decorated signatures.
"""

import asyncio
import shlex
import sys
from dataclasses import replace
from importlib.metadata import version

from ctui import CommandError, CommandResult, ConfirmationRequired, CtuiApp

from ctmodbus.client_commands import ClientCommandMixin
from ctmodbus.component_help import ComponentHelpMixin
from ctmodbus.connection import Connection, ConnectionSettings, create_client
from ctmodbus.data_state import DataState
from ctmodbus.operations import ModbusCommandMixin
from ctmodbus.polling import TABLE_ARGUMENTS, Poll, PollCommandMixin
from ctmodbus.proxy_commands import ProxyCommandMixin
from ctmodbus.result_popups import result_title, show_result
from ctmodbus.server import Server
from ctmodbus.server_commands import ServerCommandMixin
from ctmodbus.tag_deletion import TagDeletionMixin
from ctmodbus.tags import TagCommandMixin, TagStore, parse_tag_document


class ModbusApp(  # pylint: disable=too-many-public-methods,too-many-ancestors
    ComponentHelpMixin,
    ClientCommandMixin,
    ProxyCommandMixin,
    PollCommandMixin,
    ServerCommandMixin,
    TagDeletionMixin,
    TagCommandMixin,
    ModbusCommandMixin,
    CtuiApp,
):
    """A Modbus client with one connection and project-scoped services.

    Open the backend before direct dispatch, or use run/run_cli for managed
    lifecycle. Always stop device work before closing the backend. Connection
    commands validate ConnectionSettings and share open_connection's return
    and failure contracts; decorators define CLI names and named options.
    The application is intended for one event loop, not concurrent threads.
    """

    name = "ctmodbus"
    version = version("ctmodbus")
    description = "An asynchronous Modbus tool for device testing"
    prompt = "ctmodbus> "
    app_id = "io.controlthings.ctmodbus"
    project_schema_version = 2
    project_migrations = {1: (TagStore.CREATE,)}

    def __init__(self, *, client_factory=create_client, **kwargs):
        """Register project templates and runtime guards without opening I/O.

        Forward kwargs to CtuiApp; inject a sync/async client factory for tests.
        TagStore uses the configured backend, which must support project SQL.
        """
        super().__init__(**kwargs)
        self.selected_client_settings = None
        self.client_config_source = None
        self.client_config_saved = None
        self._client_config_task = None
        self._component_stop_task = None
        self.connection = Connection(client_factory)
        self.tags = TagStore(self.backend)
        self.server = Server(self)
        self.poller = Poll(self)
        self._poll_orders = {}
        self._poll_start_task = None
        self._poll_stdout = None
        self._cli_failed = False
        self._cli_exit_requested = False
        self._result_popup_task = None
        self._result_popup_tasks = set()
        self._result_popup_lock = asyncio.Lock()
        self.client_state = DataState()
        self._server_edit_task = None
        self._prepared_server_imports = {}
        self.statusbar = self.connection_status
        self._device_dispatches = set()
        self._project_changing = False
        self._prepared_tag_deletions = {}
        self._tag_delete_task = None
        self._tag_import_task = None
        self._tag_mutations = set()
        self._prepared_tag_imports = {}
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

    def append_output(self, text: str) -> None:
        """Append runtime output synchronously to TUI/WUI or the active CLI stream.

        Read the current widget at append time. No await permits competing tasks
        to interleave a read/modify/write; callers supply safely rendered text.
        """
        if self._poll_stdout is not None:
            print(text, file=self._poll_stdout, flush=True)
            return
        layout = getattr(self, "layout", None)
        current = layout.output_field.text if layout else self.output_text
        self.output_text = f"{current.rstrip()}\n{text}" if current else text
        if layout:
            layout.set_output(self.output_text)
        runtime = getattr(self, "app", None)
        if runtime:
            runtime.invalidate()

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
        return (
            f"Project: {project} | {state}{self._progress} | "
            f"Server: {self.server.label}"
        )

    def update_progress(self, completed, total):
        """Set completed/total footer progress; total=0 clears it; return None.

        Invalidate the TUI only if its runtime has been built; CLI is unaffected.
        """
        self._progress = f" | Read {completed}/{total}" if total else ""
        if hasattr(self, "app"):
            self.app.invalidate()

    async def confirm_replacement(self, message, kwargs):
        """Require explicit CLI approval or invoke the TUI confirmation callback."""
        callback = kwargs.get("confirm_callback")
        if callback is None:
            raise ConfirmationRequired(message)
        approved = callback(message)
        if asyncio.iscoroutine(approved):
            approved = await approved
        return bool(approved)

    async def prepare_tag_import(self, text, kwargs):
        """Prepare exact import data under the dispatch project/tag guard.

        Use ctui parsing, including unique command prefixes and end-of-options.
        Confirm collisions against validated data, then retain that data for this
        task. The import command consumes it without rereading the file.
        """
        item, arguments = self.commands.resolve(text)
        values = item.parse_args(arguments)
        imported = parse_tag_document(values["path"].expanduser())
        replace_existing = values.get("replace", False)
        collisions = sorted({tag.name for tag in imported} & await self.tags.names())
        if collisions and not replace_existing:
            message = (
                "Tags already exist: "
                + ", ".join(collisions)
                + ". Overwrite them? Re-run with --replace to overwrite "
                "without prompting."
            )
            if not await self.confirm_replacement(message, kwargs):
                return CommandResult.rejected()
            replace_existing = True
        self._prepared_tag_imports[asyncio.current_task()] = (
            imported,
            replace_existing,
        )
        return None

    async def dispatch(self, text, **kwargs):
        """Execute shared dispatch, then present owned management results in UI.

        Result dialogs preserve the output pane and run after lifecycle guards
        release. Reject another submission until dismissed. CLI failures and
        explicit exit requests disable server keepalive during normal teardown.
        """
        if self._result_popup_task is not None:
            raise CommandError(
                "Dismiss the result popup before starting another command"
            )
        try:
            result = await self.dispatch_modbus(text, **kwargs)
        except BaseException:
            if self._poll_stdout is not None:
                self._cli_failed = True
            raise
        if result.exit_requested:
            self._cli_exit_requested = True
        title = result_title(self.commands.resolve(text)[0].name)
        if (
            title
            and result.accepted
            and result.output is not None
            and self._poll_stdout is None
            and getattr(self, "app", None) is not None
        ):
            await self.present_result_popup(title, result.output)
            return replace(result, output=None, append_output=False)
        return result

    async def present_result_popup(self, title: str, text: str) -> None:
        """Serialize standard message dialogs and track their lifetime for shutdown."""
        task = asyncio.current_task()
        self._result_popup_tasks.add(task)
        try:
            async with self._result_popup_lock:
                self._result_popup_task = task
                try:
                    await show_result(title, text)
                finally:
                    self._result_popup_task = None
        finally:
            self._result_popup_tasks.discard(task)

    # Lifecycle arbitration is intentionally centralized around command dispatch.
    async def dispatch_modbus(  # pylint: disable=too-many-branches,too-many-statements
        self, text, **kwargs
    ):
        """Return the ctui result for text while arbitrating device lifecycle.

        Reject project transitions during tracked device work/open connections,
        and device work during opening, closing, or stopping. Attach recording
        warnings to success or CommandError without disguising acknowledged
        writes. Cancellation inside execution becomes CommandError. shlex errors
        precede that boundary. Imports reserve the project and tag mutations across
        confirmation and application; other commands remain available.
        """
        tokens = shlex.split(text)

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
            ("client start", "client config ", "read ", "write ")
        )
        poll_start = item.name in {"poll tags", "poll raw"}
        device_command = device_command or poll_start
        server_import = item.name == "server config import"
        server_start = item.name in {
            "server start tcp",
            "server start udp",
            "server start tls",
            "server start rtu",
            "server start ascii",
        }
        server_edit = (
            (
                item.name.startswith("server config ")
                and item.name
                not in {
                    "server config show",
                    "server config export",
                    "server config validate",
                    "server reset",
                }
            )
            or item.name.startswith("server hook ")
            or server_start
        )
        task = asyncio.current_task()
        if item.name == "proxy start" and (
            self._opening
            or self._closing
            or self.server.lifecycle.locked()
            or self.server.stopping
        ):
            raise CommandError(
                "Finish client/server lifecycle changes before starting the proxy"
            )
        client_config = item.name.startswith("client config ")
        if self._client_config_task is not None and (
            client_config
            or item.name.startswith("client start")
            or project_change
            or item.name == "client stop"
        ):
            raise CommandError(
                "Client configuration is changing; retry when it finishes"
            )
        if (
            item.name == "server stop"
            and self._server_edit_task is not None
            and self.server.listener is None
        ):
            raise CommandError(
                "Server configuration is changing; retry when it finishes"
            )
        component_stop = item.name in {"client stop", "server stop"}
        if self._component_stop_task is not None and (
            project_change
            or item.name.startswith(
                (
                    "client start",
                    "client config ",
                    "server start",
                    "server config ",
                    "server hook ",
                    "server reset",
                    "proxy ",
                )
            )
            or component_stop
        ):
            raise CommandError("A component is stopping; retry when it finishes")
        if self._stopping:
            raise CommandError("Application is stopping")
        importing = item.name == "tags import"
        tag_mutation = item.name in {
            "tags create",
            "tags rename",
            "tags delete",
            "tags import",
        }
        deleting = item.name == "tags delete"
        if self._tag_delete_task is not None and (
            project_change or tag_mutation or server_edit
        ):
            raise CommandError("Tag deletion is in progress; retry when it finishes")
        if deleting and self._tag_mutations and self._tag_import_task is None:
            raise CommandError("Tag edits are in progress; retry when they finish")
        if poll_start and self._poll_start_task is not None:
            raise CommandError("A poll is already starting")
        if (self.poller.active or self._poll_start_task is not None) and tag_mutation:
            raise CommandError("Stop polling before changing tag definitions")
        if poll_start and (self._tag_mutations or self._tag_import_task is not None):
            raise CommandError("Finish tag edits before starting polling")
        if self.poller.active and project_change:
            raise CommandError("Stop polling before changing projects")
        if self._server_edit_task is not None and (
            project_change or tag_mutation or server_edit
        ):
            raise CommandError(
                "Server configuration is changing; retry when it finishes"
            )
        if self.server.stopping and (project_change or tag_mutation or server_edit):
            raise CommandError("Server is stopping; retry when it finishes")
        if self.server.listener is not None and (
            project_change or tag_mutation or server_edit
        ):
            raise CommandError(
                "Stop the server before changing its configuration, tags or project"
            )
        if server_edit and (self._tag_mutations or self._tag_import_task is not None):
            raise CommandError(
                "Finish tag edits before changing the server configuration"
            )
        if self._tag_import_task is not None and (
            project_change or tag_mutation or server_edit
        ):
            raise CommandError("Tag import is in progress; retry when it finishes")
        if importing and self._tag_mutations:
            raise CommandError("Tag edits are in progress; retry when they finish")
        if project_change:
            if (
                self._project_changing
                or self._device_dispatches
                or self._tag_mutations
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
            "client start tcp",
            "client start tls",
            "client start udp",
            "client start rtu",
            "client start ascii",
            "client start",
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
        if server_edit:
            self._server_edit_task = task
        if tag_mutation:
            self._tag_mutations.add(task)
        if deleting:
            self._tag_delete_task = task
        if importing:
            self._tag_import_task = task
        if poll_start:
            self._poll_start_task = task
        if item.name == "poll raw":
            order = []
            for token in tokens:
                flag = token.split("=", 1)[0]
                matches = [
                    name
                    for name, argument in TABLE_ARGUMENTS.items()
                    if flag.startswith("--") and argument.flags[0].startswith(flag)
                ]
                if len(matches) == 1 and matches[0] not in order:
                    order.append(matches[0])
            self._poll_orders[task] = order
        if client_config:
            self._client_config_task = task
        if component_stop:
            self._component_stop_task = task
        try:
            if deleting:
                rejected = await self.prepare_tag_deletion(text, kwargs)
                if rejected is not None:
                    return rejected
            if component_stop and self.server.proxy:
                _, arguments = self.commands.resolve(text)
                values = item.parse_args(arguments)
                if not values.get("confirm", False):
                    if not await self.confirm_replacement(
                        "Proxy is running. Stop the proxy and this component? "
                        "Use --confirm to approve without prompting.",
                        kwargs,
                    ):
                        return CommandResult.rejected()
                self.server.proxy = False
            if server_import:
                rejected = await self.prepare_server_import(text, kwargs)
                if rejected is not None:
                    return rejected
            if importing:
                rejected = await self.prepare_tag_import(text, kwargs)
                if rejected is not None:
                    return rejected
            if project_change:
                # External task cancellation can leave an ended transport's
                # recording session open; finish it in its original project.
                await self.finish_record_session()
            result = await super().dispatch(text, **kwargs)
            if project_change and result.accepted:
                self.server.simulator = None
                self.server.state = DataState("No server session")
                self.client_state = DataState()
                self.selected_client_settings = None
                self.client_config_source = None
                self.client_config_saved = None
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
            if client_config:
                self._client_config_task = None
            if component_stop:
                self._component_stop_task = None
            self._poll_orders.pop(task, None)
            if poll_start:
                self._poll_start_task = None
            if server_edit:
                self._server_edit_task = None
                self._prepared_server_imports.pop(task, None)
            if tag_mutation:
                self._tag_mutations.discard(task)
            if deleting:
                self._tag_delete_task = None
                self._prepared_tag_deletions.pop(task, None)
            if importing:
                self._prepared_tag_imports.pop(task, None)
                self._tag_import_task = None
            if project_change:
                self._project_changing = False
            if device_command:
                self._device_dispatches.discard(task)
            if opening:
                self._opening = False
            self._record_warnings.pop(task, None)

    async def record_operation(self, direction, decoded):
        """Append decoded data to the current Modbus record session; return None.

        No session means no record. Catch ordinary storage errors as task-local
        warnings so an acknowledged write never looks like a failed protocol
        operation and invites a duplicate write. Cancellation still propagates.
        """
        self.client_state.record(direction, decoded)
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
        """Clear the active session ID and await optional end_session; return None.

        Repeated calls are harmless; storage errors propagate after the ID is
        cleared. Call before switching project storage to keep records isolated.
        """
        session, self._record_session = self._record_session, None
        end_session = getattr(self.records, "end_session", None)
        if session is not None and end_session is not None:
            await end_session(session)

    async def close_connection(self):
        """Cancel tracked device dispatches and clear transport/session state.

        Serialize close calls, wait up to five seconds for task draining, and
        abort the transport even on drain failure. Return None; TimeoutError or
        record-session cleanup errors can propagate. Always clear footer progress.
        """
        async with self._close_lock:
            self._closing = True
            try:
                pending = (self._device_dispatches | self.connection.tasks) - {
                    asyncio.current_task()
                }
                for task in pending:
                    task.cancel()
                try:
                    await asyncio.wait_for(self.poller.stop(abort=True), timeout=5)
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

    async def run_cli(self, arguments, *, stdout=None, stderr=None, program=None):
        """Run CLI commands, then keep a remaining server alive until stopped.

        Stream runtime rows to stdout. ctui owns parsing, errors, and storage
        lifetime. Successful sequences wait in on_stop; failures or explicit exit
        clean up immediately. Cancellation/Ctrl-C always drains both endpoints.
        """
        self._poll_stdout = stdout or sys.stdout
        self._cli_failed = False
        self._cli_exit_requested = False
        try:
            return await super().run_cli(
                arguments, stdout=stdout, stderr=stderr, program=program
            )
        finally:
            self._poll_stdout = None

    async def on_start(self):
        """Allow a fresh runtime to use this application instance."""
        self._stopping = False

    async def on_stop(self):
        """Keep successful CLI servers alive, then always drain runtime resources."""
        try:
            if (
                self._poll_stdout is not None
                and not self._cli_failed
                and not self._cli_exit_requested
                and self.server.listener is not None
            ):
                self._poll_stdout.flush()
                await self.server.stop_event.wait()
        finally:
            await self.stop_runtime()

    async def stop_runtime(self):
        """Reject dispatch and cancel UI/management tasks before closing services."""
        self._stopping = True
        pending = (
            self._tag_mutations
            | self._result_popup_tasks
            | {
                task
                for task in (
                    self._tag_import_task,
                    self._server_edit_task,
                    self._client_config_task,
                    self._component_stop_task,
                    self._result_popup_task,
                )
                if task is not None
            }
        )
        pending.discard(asyncio.current_task())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 5)
        await self.server.stop()
        await self.close_connection()
