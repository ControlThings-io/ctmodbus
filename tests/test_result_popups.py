"""Management result presentation and CLI server keepalive regression contracts."""

import asyncio
import io
import os
import signal
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_commands
from ctui import CommandError
from pymodbus.client import AsyncModbusTcpClient

from ctmodbus.app import ModbusApp
from ctmodbus.result_popups import result_title


def free_port():
    """Return a loopback port candidate; actual binding still validates availability."""
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


class ResultPopupTests(unittest.IsolatedAsyncioTestCase):
    """Management results preserve the output pane and await standard dialogs."""

    asyncSetUp = test_commands.CommandTests.asyncSetUp
    asyncTearDown = test_commands.CommandTests.asyncTearDown

    async def test_start_popup_preserves_output_and_request_logging(self):
        """A live server accepts and logs requests before its result popup is dismissed."""
        self.app.app = type("Runtime", (), {"invalidate": lambda self: None})()
        self.app.output_text = "Existing output"
        opened, dismissed = asyncio.Event(), asyncio.Event()
        port = free_port()

        async def dialog(title, text):
            self.assertEqual(title, "Server started")
            self.assertIn("TCP", text)
            self.assertIsNotNone(self.app.server.listener)
            opened.set()
            await dismissed.wait()

        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        with patch("ctmodbus.app.show_result", dialog):
            task = asyncio.create_task(
                self.app.dispatch(f"server start tcp 127.0.0.1 --port {port}")
            )
            try:
                await asyncio.wait_for(opened.wait(), 2)
                self.assertFalse(task.done())
                with self.assertRaisesRegex(CommandError, "Dismiss"):
                    await self.app.dispatch("server status")
                self.assertTrue(await client.connect())
                self.assertFalse(
                    (await client.read_coils(0, count=1, device_id=1)).isError()
                )
                self.assertTrue(self.app.output_text.startswith("Existing output\n"))
                self.assertIn("SERVER #1", self.app.output_text)
            finally:
                dismissed.set()
                client.close()
            result = await asyncio.wait_for(task, 2)
        self.assertIsNone(result.output)
        self.assertIsNone(self.app._result_popup_task)

    async def test_popup_shutdown_cancels_presentation(self):
        """Shutdown releases an open popup without undoing a completed configuration edit."""
        self.app.app = type("Runtime", (), {"invalidate": lambda self: None})()
        opened = asyncio.Event()

        async def dialog(title, text):
            opened.set()
            await asyncio.Event().wait()

        with patch("ctmodbus.app.show_result", dialog):
            task = asyncio.create_task(
                self.app.dispatch(
                    "client config set --transport tcp --target localhost"
                )
            )
            await opened.wait()
            await self.app.on_stop()
            self.assertTrue(task.cancelled())
            self.assertIsNone(self.app._result_popup_task)
            self.assertEqual(self.app.selected_client_settings.target, "localhost")

    def test_scope_and_descriptive_titles(self):
        """Only agreed owned management commands use result popups."""
        for command in (
            "client start tcp",
            "client stop",
            "client discover",
            "client config set",
            "client config save",
            "client config load",
            "client config show",
            "server status",
            "server config export",
            "server hook tick",
            "proxy logging",
            "tags list",
            "tags create",
            "tags rename",
            "tags delete",
            "tags show",
            "tags import",
            "tags export",
            "server reset",
            "server config clear",
            "poll status",
            "poll stop",
        ):
            self.assertIsNotNone(result_title(command), command)
        for command in (
            "read coils",
            "write tag",
            "poll tags",
            "poll raw",
            "project configs show",
            "history export",
            "project import",
            "client",
            "server",
            "proxy",
        ):
            self.assertIsNone(result_title(command), command)
        self.assertEqual(result_title("tags import"), "Tags imported")
        self.assertEqual(
            result_title("client config show"), "Client configuration details"
        )


class CliKeepaliveTests(unittest.IsolatedAsyncioTestCase):
    """CLI executes its complete sequence before retaining any remaining listener."""

    async def test_sequence_then_keepalive_and_cancellation_cleanup(self):
        """Later reads run before keepalive; cancellation closes client, server, and backend."""
        with tempfile.TemporaryDirectory() as folder:
            app = ModbusApp(data_dir=folder)
            port = free_port()
            stdout, stderr = io.StringIO(), io.StringIO()
            ready = asyncio.Event()
            keeping_alive = asyncio.Event()
            original_stop = app.on_stop

            async def observe_stop():
                keeping_alive.set()
                await original_stop()

            app.on_stop = observe_stop
            app.on(
                "command_finished",
                lambda command, result: (
                    ready.set() if command.name == "read coils" else None
                ),
            )
            task = asyncio.create_task(
                app.run_cli(
                    [
                        "-c",
                        f"server start tcp 127.0.0.1 --port {port}",
                        "-c",
                        f"client start tcp 127.0.0.1 --port {port}",
                        "-c",
                        "read coils 0",
                        "-c",
                        "client stop",
                    ],
                    stdout=stdout,
                    stderr=stderr,
                )
            )
            try:
                await asyncio.wait_for(ready.wait(), 3)
                await asyncio.wait_for(keeping_alive.wait(), 3)
                self.assertIsNone(app.connection.client)
                self.assertFalse(task.done())
                self.assertIsNotNone(app.server.listener)
                self.assertIn("Read coils", stdout.getvalue())
                self.assertEqual(stderr.getvalue(), "")
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertIsNone(app.server.listener)
            self.assertIsNone(app.connection.client)
            self.assertIsNone(app._poll_stdout)

    async def test_explicit_stop_error_and_exit_skip_keepalive(self):
        """Explicit stop/exit and both expected/unexpected failures clean up promptly."""
        for ending, status in (
            ("server stop", 0),
            ("invalid command", 2),
            ("exit confirm", 0),
            ("client discover", 1),
        ):
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as folder:
                app = ModbusApp(data_dir=folder)
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch(
                    "ctmodbus.client_commands.suggestions",
                    side_effect=RuntimeError("discovery failed"),
                ):
                    result = await asyncio.wait_for(
                        app.run_cli(
                            [
                                "-c",
                                f"server start tcp 127.0.0.1 --port {free_port()}",
                                "-c",
                                ending,
                            ],
                            stdout=stdout,
                            stderr=stderr,
                        ),
                        3,
                    )
                self.assertEqual(result, status, stderr.getvalue())
                self.assertIsNone(app.server.listener)
                self.assertIsNone(app.connection.client)
                self.assertIsNone(app._poll_stdout)

    @unittest.skipUnless(os.name == "posix", "SIGINT subprocess check requires POSIX")
    async def test_cli_ctrl_c_stops_server_without_traceback(self):
        """The real entry point stays alive, then SIGINT releases its listening socket."""
        with tempfile.TemporaryDirectory() as folder:
            port = free_port()
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "ctmodbus.commands",
                "-c",
                f"server start tcp 127.0.0.1 --port {port}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "XDG_DATA_HOME": folder},
            )
            try:
                line = await asyncio.wait_for(process.stdout.readline(), 3)
                self.assertIn(b"Server TCP", line)
                self.assertIsNone(process.returncode)
                process.send_signal(signal.SIGINT)
                _, stderr = await asyncio.wait_for(process.communicate(), 3)
                self.assertEqual(process.returncode, 130, stderr.decode())
                self.assertNotIn(b"Traceback", stderr)
                with socket.socket() as released:
                    released.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    released.bind(("127.0.0.1", port))
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
