"""Polling cadence, output, lifecycle, limits, and read-evidence regressions."""

import asyncio
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ctui import CommandError
from test_commands import FakeClient, response

from ctmodbus.app import ModbusApp


def unpad(text):
    """Normalize table padding for behavioral assertions independent of widths."""
    return "\n".join(
        " | ".join(cell.strip() for cell in line.split("|"))
        for line in text.splitlines()
    )


class PollingTests(unittest.IsolatedAsyncioTestCase):
    """Run shared dispatch with isolated project storage and controllable device I/O."""

    async def asyncSetUp(self):
        """Open project and fake connection; retain output without a UI runtime."""
        self.directory = tempfile.TemporaryDirectory()
        self.client = FakeClient()
        self.app = ModbusApp(
            data_dir=self.directory.name, client_factory=lambda settings: self.client
        )
        await self.app.backend.open()
        await self.app.dispatch("client start tcp localhost")

    async def asyncTearDown(self):
        """Drain polling and device work before closing isolated project storage."""
        await self.app.on_stop()
        await self.app.backend.close()
        self.directory.cleanup()

    async def finish(self):
        """Bound the background poll to avoid a hung regression run."""
        await asyncio.wait_for(self.app.poller.task, 3)

    async def test_raw_order_format_limits_and_records(self):
        """Keep table/range order, duplicates, compact values, and shared records."""
        self.app.output_text = "Existing output"
        await self.app.dispatch(
            "poll raw --holding-registers 2-3,1,2 --coils 0-2 --count 2 --interval 0.02"
        )
        await self.finish()
        lines = unpad(self.app.output_text).splitlines()
        self.assertEqual(lines[0], "Existing output")
        self.assertEqual(
            lines[1],
            "# | holding_registers:2-3 | holding_registers:1 | holding_registers:2 | coils:0-2",
        )
        self.assertEqual(lines[2], "1 | 0002 0003 | 0001 | 0002 | 111")
        self.assertEqual(lines[3], "2 | 0002 0003 | 0001 | 0002 | 111")
        self.assertEqual(self.app.poller.completed, 2)
        self.assertEqual(len(await self.app.records.query(direction="received")), 8)
        self.assertEqual(self.client.peak, 1)

    async def test_tags_all_explicit_order_types_and_guards(self):
        """Snapshot all tags in name order or explicit order and reject mutations."""
        await self.app.dispatch("tags create z coil 0 bool")
        await self.app.dispatch("tags create a holding_register 1 int16")
        self.client.gate = asyncio.Event()
        await self.app.dispatch("poll tags --count 1")
        await asyncio.wait_for(self.client.started.wait(), 1)
        for text in (
            "poll tags",
            "tags delete a",
            "tags create x coil 4 bool",
            "tags import missing.toml",
            "project load other",
        ):
            with self.subTest(command=text), self.assertRaises(CommandError):
                await self.app.dispatch(text)
        self.client.gate.set()
        await self.finish()
        self.assertIn("# | a | z\n1 | 1 | True", unpad(self.app.output_text))
        await self.app.dispatch("poll tags z,a,z --count 1")
        await self.finish()
        self.assertIn("# | z | a | z\n1 | True | 1 | True", unpad(self.app.output_text))

    async def test_fixed_cadence_skips_inflight_and_manual_work(self):
        """A slow response skips ticks without overlapping or adding response delay."""
        starts = []
        original = self.client.read_coils

        async def delayed(**kwargs):
            starts.append(asyncio.get_running_loop().time())
            if len(starts) == 1:
                await asyncio.sleep(0.14)
            return await original(**kwargs)

        self.client.read_coils = delayed
        await self.app.dispatch("poll raw --coils 0 --interval 0.05 --count 3")
        await self.finish()
        self.assertGreaterEqual(self.app.poller.skipped, 2)
        self.assertLess(starts[1] - starts[0], 0.19)
        self.assertGreater(starts[1] - starts[0], 0.13)
        self.assertEqual(self.app.poller.completed, 3)
        async with self.app.connection.operation():
            await self.app.dispatch(
                "poll raw --coils 0 --interval 0.01 --duration 0.04"
            )
            await self.finish()
        self.assertEqual(self.app.poller.started, 0)
        self.assertGreaterEqual(self.app.poller.skipped, 1)

    async def test_partial_column_error_and_continue(self):
        """Retain confirmed chunks and continue other columns and subsequent cycles."""

        def replies(name, kwargs):
            if kwargs["address"] == 125:
                return response(function_code=3, registers=[])
            return response(
                function_code=3, registers=[kwargs["address"]] * kwargs["count"]
            )

        self.client.reply = replies
        await self.app.dispatch(
            "poll raw --holding-registers 0-125,7 --count 2 --interval 0.01"
        )
        await self.finish()
        rows = [
            line
            for line in unpad(self.app.output_text).splitlines()
            if line.startswith(("1 | ", "2 | "))
        ]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row.endswith("ERR | 0007"))
            self.assertEqual(row.count("0000"), 125)
        self.assertEqual(self.app.poller.failed_columns, 2)
        self.assertEqual(len(await self.app.records.query(direction="error")), 2)

    async def test_graceful_stop_and_abort_idle_or_inflight(self):
        """Stop drains without closing; cancel stops even an idle timer and closes I/O."""
        self.client.gate = asyncio.Event()
        await self.app.dispatch("poll raw --coils 0 --interval 0.01")
        await asyncio.wait_for(self.client.started.wait(), 1)
        stopping = asyncio.create_task(self.app.dispatch("poll stop"))
        await asyncio.sleep(0.03)
        self.assertFalse(stopping.done())
        self.client.gate.set()
        await asyncio.wait_for(stopping, 1)
        self.assertEqual(self.app.poller.started, 1)
        self.assertTrue(self.client.connected)
        self.client.gate = None
        await self.app.dispatch("poll raw --coils 0 --interval 60")
        await asyncio.sleep(0.02)
        await self.app.dispatch("client stop")
        self.assertFalse(self.app.poller.active)
        self.assertFalse(self.client.connected)
        await self.app.dispatch("client start tcp localhost")
        self.client.gate = asyncio.Event()
        self.client.started.clear()
        await self.app.dispatch("poll raw --coils 0")
        await asyncio.wait_for(self.client.started.wait(), 1)
        await asyncio.wait_for(self.app.dispatch("client stop"), 1)
        self.assertFalse(self.app.poller.active)
        self.assertIn("ERR", unpad(self.app.output_text))

    async def test_duration_and_invalid_plans_before_io(self):
        """Both limits apply and invalid selections/options do not start I/O."""
        for text in (
            "poll raw",
            "poll tags",
            "poll tags missing",
            "poll raw --coils 65536",
            "poll raw --coils 0 --interval 0",
            "poll raw --coils 0 --interval nan",
            "poll raw --coils 0 --duration -1",
            "poll raw --coils 0 --count 0",
        ):
            with self.subTest(command=text), self.assertRaises(CommandError):
                await self.app.dispatch(text)
        self.assertEqual(self.client.calls, [])
        await self.app.dispatch(
            "poll raw --coils 0 --interval 0.01 --duration 0.035 --count 100"
        )
        await self.finish()
        self.assertGreater(self.app.poller.completed, 0)
        self.assertLess(self.app.poller.completed, 100)
        result = await self.app.dispatch("poll status")
        self.assertIn("Stopped", result.output)
        self.assertIn("Duration limit reached", result.output)

    async def test_connection_loss_stops_and_marks_remaining_columns(self):
        """Disconnected transport produces error columns and ends the poll."""

        def disconnect(_name, _kwargs):
            self.client.connected = False
            raise CommandError("Connection lost")

        self.client.reply = disconnect
        await self.app.dispatch("poll raw --coils 0,1 --interval 0.01")
        await self.finish()
        self.assertIn("1 | ERR | ERR", unpad(self.app.output_text))
        self.assertEqual(self.app.poller.started, 1)

    async def test_ui_output_and_cli_streaming(self):
        """Shared layout output appends and invalidates; CLI limits stream in sequence."""
        field = SimpleNamespace(text="Earlier output")
        self.app.layout = SimpleNamespace(
            output_field=field, set_output=lambda text: setattr(field, "text", text)
        )
        redraws = []
        self.app.app = SimpleNamespace(invalidate=lambda: redraws.append(True))
        await self.app.dispatch("poll raw --coils 0 --count 1")
        await self.finish()
        self.assertTrue(unpad(field.text).startswith("Earlier output\n#"))
        self.assertIn("1 | 1", unpad(field.text))
        self.assertGreaterEqual(len(redraws), 3)
        del self.app.app
        del self.app.layout
        output = io.StringIO()
        self.app._poll_stdout = output
        await self.app.dispatch("poll raw --coils 0 --count 2 --interval 0.01")
        self.app._poll_stdout = None
        self.assertIn("2 | 1", unpad(output.getvalue()))
        self.assertFalse(self.app.poller.active)

    async def test_start_guard_and_immediate_close(self):
        """Protect target resolution from tag edits; immediate close drains newborn tasks."""
        await self.app.dispatch("tags create x coil 0 bool")
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.app.tags.list

        async def paused():
            entered.set()
            await release.wait()
            return await original()

        with patch.object(self.app.tags, "list", paused):
            starting = asyncio.create_task(self.app.dispatch("poll tags --count 1"))
            await entered.wait()
            for text in ("tags delete x", "poll tags"):
                with self.assertRaises(CommandError):
                    await self.app.dispatch(text)
            release.set()
            await starting
        await self.app.dispatch("client stop")
        self.assertFalse(self.client.connected)
        self.assertFalse(self.app.poller.active)

    async def test_cli_lifecycle_and_web_runtime(self):
        """Real CLI lifecycle and browser layout retain appended background rows."""
        from ctui.web import WebSession

        with tempfile.TemporaryDirectory() as folder:
            app = ModbusApp(
                data_dir=folder, client_factory=lambda settings: FakeClient()
            )
            stdout, stderr = io.StringIO(), io.StringIO()
            result = await app.run_cli(
                [
                    "-c",
                    "client start tcp localhost",
                    "-c",
                    "poll raw --coils 0 --count 2 --interval 0.01",
                    "-c",
                    "poll status",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(result, 0, stderr.getvalue())
            self.assertIn("2 | 1", unpad(stdout.getvalue()))
            self.assertIn("completed=2", unpad(stdout.getvalue()))
            self.assertFalse(app.connection.connected)
        session = WebSession(self.app, port=0, stdout=io.StringIO())
        try:
            await session.start()
            session.apply_result(
                await self.app.dispatch(
                    "poll raw --coils 0 --duration 0.035 --interval 0.01"
                )
            )
            await self.finish()
            self.assertIn("# | coils:0", unpad(self.app.layout.output_field.text))
            self.assertIn("1 | 1", unpad(self.app.layout.output_field.text))
            self.assertEqual(self.app.app, session)
        finally:
            await session.close()

    async def test_typed_values_and_tag_error_columns(self):
        """Render signed/float codecs and exception columns without stopping later reads."""
        from ctmodbus.tags import encode_tag_value

        await self.app.dispatch("tags create signed holding_register 0 int16")
        await self.app.dispatch("tags create energy input_register 5 float32")
        await self.app.dispatch("tags create bad holding_register 9 uint16")
        tag = await self.app.tags.get("energy")

        def replies(name, kwargs):
            if kwargs["address"] == 9:
                return SimpleNamespace(isError=lambda: True)
            return response(
                function_code=4 if name == "read_input_registers" else 3,
                registers=(
                    encode_tag_value(tag, 12.75) if kwargs["address"] == 5 else [65535]
                ),
            )

        self.client.reply = replies
        await self.app.dispatch("poll tags signed,bad,energy --count 2 --interval 0.01")
        await self.finish()
        self.assertIn("1 | -1 | ERR | 12.75", unpad(self.app.output_text))
        self.assertIn("2 | -1 | ERR | 12.75", unpad(self.app.output_text))
        self.assertEqual(self.app.poller.failed_columns, 2)

    async def test_cli_interruption_propagates_to_dispatch(self):
        """Cancellation becomes a command error so CLI dispatch stops its sequence."""
        output = io.StringIO()
        self.client.gate = asyncio.Event()
        self.app._poll_stdout = output
        task = asyncio.create_task(self.app.dispatch("poll raw --coils 0"))
        await self.client.started.wait()
        task.cancel()
        with self.assertRaises(CommandError):
            await task
        self.app._poll_stdout = None
        self.assertFalse(self.app.poller.active)
        self.assertFalse(self.client.connected)


class PollTableTests(unittest.TestCase):
    """Check real separator positions, type bounds, and append-only expansion."""

    def test_alignment_and_type_widths(self):
        """Mixed values and ERR retain separator positions across every row."""
        from ctui import IntegerSpan

        from ctmodbus.polling import PollColumn, PollTable
        from ctmodbus.tags import Tag

        columns = (
            PollColumn(
                "n",
                "holding_registers",
                (IntegerSpan(0, 1),),
                Tag("n", "holding_registers", 0, "int16"),
            ),
            PollColumn(
                "b", "coils", (IntegerSpan(0, 1),), Tag("b", "coils", 0, "bool")
            ),
            PollColumn("raw", "holding_registers", (IntegerSpan(0, 3),)),
        )
        table = PollTable(columns, 100)
        header = table.header()
        self.assertEqual(header, "  # |      n | b     | raw")
        rows = [
            table.row(1, ["1", "True", "0000 0001 0002"])[0],
            table.row(100, ["-32768", "False", "0000 ERR"])[0],
        ]
        positions = lambda text: [i for i, char in enumerate(text) if char == "|"]
        self.assertEqual(positions(header), [4, 13, 21])
        for row in rows:
            self.assertEqual(positions(row), positions(header))
        self.assertTrue(rows[0].startswith("  1 |      1 | True  | "))
        self.assertTrue(rows[1].startswith("100 | -32768 | False | "))
        self.assertEqual(len(rows[0].split(" | ")[-1]), 14)

    def test_expansion_and_float_precision(self):
        """Counter/value overflow repeats a wider header; floats remain compact."""
        from ctui import IntegerSpan

        from ctmodbus.polling import PollColumn, PollTable
        from ctmodbus.tags import Tag

        tag = Tag("f", "holding_registers", 0, "float64")
        table = PollTable(
            (PollColumn("f", tag.table, (IntegerSpan(0, 4),), tag),), None
        )
        self.assertEqual(table.widths[0], 6)
        old = table.row(1, ["1.0"])[0]
        expanded = table.row(1000000, ["X" * 26])
        self.assertEqual(len(expanded), 2)
        self.assertEqual(expanded[0].split(" | ")[0], "      #")
        self.assertEqual(expanded[1], "1000000 | " + "X" * 26)
        self.assertEqual(old.split(" | ")[0], "     1")
        self.assertEqual(len(table.row(1000001, ["ERR"])), 1)
        for value in (1.0, -1.2345678901234567, 1.7976931348623157e308):
            self.assertEqual(float(table.tag_value(tag, value)), value)
        self.assertEqual(table.tag_value(tag, 1.0), "1.0")
        self.assertEqual(table.tag_value(tag, 1e100), "1e+100")
