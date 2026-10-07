"""Exercise the actual ctui terminal runtime with an injected terminal."""

import asyncio
import tempfile
import unittest
from unittest.mock import patch

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from test_commands import FakeClient

from ctmodbus.app import ModbusApp


class TerminalTests(unittest.IsolatedAsyncioTestCase):
    """Drive the real TUI with pipe input and dummy output, without a physical terminal."""

    async def test_terminal_commands_and_shutdown(self):
        """Await command completion events and verify exit closes the fake connection."""
        ready = asyncio.Event()
        finished = asyncio.Queue()

        class TestApp(ModbusApp):
            """Expose terminal readiness to the surrounding asynchronous test."""

            async def on_ready(self):
                """Signal that input may be injected; return None."""
                ready.set()

        with tempfile.TemporaryDirectory() as path, create_pipe_input() as pipe:
            client = FakeClient()
            app = TestApp(data_dir=path, client_factory=lambda settings: client)
            app.on(
                "command_finished",
                lambda command, result: finished.put_nowait(command.name),
            )
            with create_app_session(input=pipe, output=DummyOutput()):
                running = asyncio.create_task(app.run_async())
                try:
                    await asyncio.wait_for(ready.wait(), 3)
                    for text, name in (
                        ("client start tcp localhost", "client start tcp"),
                        ("read coils 0-2", "read coils"),
                        ("write coils 0 1", "write coils"),
                    ):
                        pipe.send_text(text + "\n")
                        self.assertEqual(
                            await asyncio.wait_for(finished.get(), 3), name
                        )
                        if name == "client start tcp":
                            while app._result_popup_task is None:
                                await asyncio.sleep(0)
                            pipe.send_text("\r")
                            while app._result_popup_task is not None:
                                await asyncio.sleep(0)
                    dialogs = asyncio.Queue()

                    async def show_overview(dialog):
                        dialogs.put_nowait(dialog)
                        return None

                    previous_output = app.layout.output_field.text
                    with patch("ctui.keybindings.show_dialog", show_overview):
                        for component in ("client", "server", "proxy"):
                            pipe.send_text(component + "\n")
                            self.assertEqual(
                                await asyncio.wait_for(finished.get(), 3), component
                            )
                            await asyncio.wait_for(dialogs.get(), 3)
                            self.assertEqual(
                                app.layout.output_field.text, previous_output
                            )
                    pipe.send_text("poll raw --coils 0-2 --interval 0.01 --count 2\n")
                    self.assertEqual(
                        await asyncio.wait_for(finished.get(), 3), "poll raw"
                    )
                    await asyncio.wait_for(app.poller.task, 3)
                    self.assertIn(
                        "2 | 111",
                        " | ".join(
                            cell.strip()
                            for cell in app.layout.output_field.text.splitlines()[
                                -2
                            ].split("|")
                        ),
                    )
                    pipe.send_text("exit confirm\n")
                    await asyncio.wait_for(running, 3)
                    self.assertFalse(client.connected)
                finally:
                    if not running.done():
                        app.exit()
                        await running
