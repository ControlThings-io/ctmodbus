"""Exercise the actual ctui terminal runtime with an injected terminal."""

import asyncio
import tempfile
import unittest

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
                        ("connect tcp localhost", "connect tcp"),
                        ("read coils 0-2", "read coils"),
                        ("write coils 0 1", "write coils"),
                    ):
                        pipe.send_text(text + "\n")
                        self.assertEqual(
                            await asyncio.wait_for(finished.get(), 3), name
                        )
                    pipe.send_text("exit\n")
                    await asyncio.wait_for(running, 3)
                    self.assertFalse(client.connected)
                finally:
                    if not running.done():
                        app.exit()
                        await running
