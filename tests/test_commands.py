"""Command and lifecycle regression tests using an injected async client."""

import asyncio
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ctui import CommandError, IntegerRanges

from ctmodbus.app import ModbusApp
from ctmodbus.connection import ConnectionSettings
from ctmodbus.formatting import format_identification, format_values
from ctmodbus.operations import read_chunks


def response(**kwargs):
    return SimpleNamespace(isError=lambda: False, **kwargs)


class FakeClient:
    def __init__(self):
        self.connected = False
        self.calls = []
        self.reply = None
        self.gate = None
        self.started = asyncio.Event()
        self.active = 0
        self.peak = 0

    async def connect(self):
        self.connected = True
        return True

    def close(self):
        self.connected = False

    def __getattr__(self, name):
        async def call(**kwargs):
            self.calls.append((name, kwargs))
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.started.set()
            try:
                if self.gate:
                    await self.gate.wait()
                if self.reply:
                    return self.reply(name, kwargs)
                if name == "read_device_information":
                    return response(
                        information={0: b"Vendor", 2: b"1.0", 128: b"custom"}
                    )
                if name.startswith("read_"):
                    count = kwargs["count"]
                    if name in ("read_coils", "read_discrete_inputs"):
                        return response(
                            function_code=1 if name == "read_coils" else 2,
                            bits=[True] * (((count + 7) // 8) * 8),
                        )
                    return response(
                        function_code=3 if name == "read_holding_registers" else 4,
                        registers=list(
                            range(kwargs["address"], kwargs["address"] + count)
                        ),
                    )
                codes = {
                    "write_coil": 5,
                    "write_coils": 15,
                    "write_register": 6,
                    "write_registers": 16,
                }
                values = kwargs.get("values", [kwargs.get("value")])
                return response(
                    function_code=codes[name],
                    address=kwargs["address"],
                    count=len(values),
                    bits=values,
                    registers=values,
                )
            finally:
                self.active -= 1

        return call


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = FakeClient()
        self.app = ModbusApp(
            data_dir=self.directory.name, client_factory=lambda settings: self.client
        )
        await self.app.backend.open()

    async def asyncTearDown(self):
        await self.app.on_stop()
        await self.app.backend.close()
        self.directory.cleanup()

    async def connect(self):
        await self.app.dispatch("connect tcp localhost --unit 7")

    async def test_all_transport_commands(self):
        for transport in ("tcp", "udp", "rtu", "ascii"):
            await self.app.dispatch(
                f"connect {transport} target --unit 7 --timeout 0.2"
            )
            self.assertEqual(self.app.connection.settings.transport, transport)
            await self.app.dispatch("close")

    async def test_range_chunking_and_unit(self):
        await self.connect()
        result = await self.app.dispatch(
            "read holding_registers 0,124-126,65535 --max-count 2"
        )
        self.assertTrue(result.append_output)
        self.assertEqual(
            [(args["address"], args["count"]) for _, args in self.client.calls],
            [(0, 1), (124, 2), (126, 1), (65535, 1)],
        )
        self.assertTrue(all(args["device_id"] == 7 for _, args in self.client.calls))

    async def test_read_types_and_bit_padding(self):
        await self.connect()
        for kind in (
            "coils",
            "discrete_inputs",
            "input_registers",
            "holding_registers",
        ):
            result = await self.app.dispatch(f"read {kind} 0-2")
            self.assertIn(f"Read {kind}", result.output)
        records = await self.app.records.query(direction="received")
        self.assertTrue(all(len(row.decoded["values"]) == 3 for row in records))

    async def test_write_functions_and_acknowledgements(self):
        await self.connect()
        for kind, values in (
            ("coils", "1"),
            ("coils", "0,1,0"),
            ("holding_registers", "65535"),
            ("holding_registers", "0,123,65535"),
        ):
            result = await self.app.dispatch(f"write {kind} 20 {values}")
            self.assertIn("Write acknowledged", result.output)
        self.assertEqual(
            [name for name, _ in self.client.calls],
            ["write_coil", "write_coils", "write_register", "write_registers"],
        )

    async def test_invalid_arguments_do_not_send(self):
        await self.connect()
        commands = [
            "read coils 65536",
            "read coils 0-2 --max-count 0",
            "read coils 0 --max-count 2001",
            "read input_registers 0 --max-count 126",
            "write coils 0 2",
            "write holding_registers 0 -1",
            "write holding_registers 0 65536",
            "write coils 65535 0,1",
            "read coils 3-1",
            "read coils nope",
            "write holding_registers 0 " + ",".join(["0"] * 124),
        ]
        for text in commands:
            with self.subTest(text=text), self.assertRaises(CommandError):
                await self.app.dispatch(text)
        self.assertEqual(self.client.calls, [])

    async def test_response_errors_and_short_reads(self):
        await self.connect()
        for reply in (
            SimpleNamespace(isError=lambda: True),
            response(function_code=3, registers=[]),
            response(function_code=3, registers=[1, 2]),
            response(function_code=3, registers=[70000]),
        ):
            self.client.reply = lambda name, args: reply
            with self.assertRaises(CommandError):
                await self.app.dispatch("read holding_registers 0")

    async def test_partial_read(self):
        await self.connect()
        self.client.reply = lambda name, args: (
            response(function_code=3, registers=[10])
            if args["address"] == 0
            else response(function_code=3, registers=[])
        )
        with self.assertRaisesRegex(
            CommandError, "Partial read: 1 addresses completed"
        ):
            await self.app.dispatch("read holding_registers 0-1 --max-count 1")

    async def test_bad_write_acknowledgements(self):
        await self.connect()
        for reply in (
            response(function_code=6, address=99, registers=[1]),
            response(function_code=6, address=0, registers=[2]),
            response(function_code=16, address=0, count=1),
            SimpleNamespace(isError=lambda: True),
        ):
            self.client.reply = lambda name, args: reply
            values = "1,2" if getattr(reply, "function_code", 0) == 16 else "1"
            with self.assertRaisesRegex(CommandError, "unconfirmed"):
                await self.app.dispatch(f"write holding_registers 0 {values}")

    async def test_sparse_identification_and_continuation(self):
        await self.connect()
        self.client.reply = lambda name, args: (
            response(information={0: b"Vendor"}, more_follows=255, next_object_id=2)
            if args["object_id"] == 0
            else response(information={2: b"1.0", 128: b"custom\x1b"})
        )
        result = await self.app.dispatch("read id")
        self.assertIn("MajorMinorRevision", result.output)
        self.assertIn("ObjectID 128", result.output)
        self.assertNotIn("\x1b", result.output)
        self.assertEqual(len(self.client.calls), 2)

    async def test_cyclic_identification(self):
        await self.connect()
        self.client.reply = lambda name, args: response(
            information={0: b"x"}, more_follows=255, next_object_id=0
        )
        with self.assertRaisesRegex(CommandError, "continuation"):
            await self.app.dispatch("read id")

    async def test_serialized_reads_and_responsive_help(self):
        await self.connect()
        self.client.gate = asyncio.Event()
        first = asyncio.create_task(self.app.dispatch("read coils 0"))
        await self.client.started.wait()
        second = asyncio.create_task(self.app.dispatch("read coils 1"))
        result = await asyncio.wait_for(self.app.dispatch("help"), 1)
        self.assertIn("read coils", result.output)
        self.client.gate.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.client.peak, 1)

    async def test_cancel_read_and_queued_work(self):
        await self.connect()
        self.client.gate = asyncio.Event()
        first = asyncio.create_task(self.app.dispatch("read coils 0"))
        await self.client.started.wait()
        second = asyncio.create_task(self.app.dispatch("read coils 1"))
        await asyncio.sleep(0)
        await asyncio.wait_for(self.app.dispatch("cancel"), 1)
        outcomes = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(all(isinstance(item, CommandError) for item in outcomes))
        self.assertEqual(len(self.client.calls), 1)
        self.assertIsNone(self.app.connection.client)
        await self.app.dispatch("project create after-cancel")

    async def test_cancel_write_reports_uncertainty(self):
        await self.connect()
        self.client.gate = asyncio.Event()
        task = asyncio.create_task(self.app.dispatch("write coils 0 1"))
        await self.client.started.wait()
        await self.app.dispatch("close")
        with self.assertRaisesRegex(CommandError, "outcome unknown"):
            await task

    async def test_cancel_connect(self):
        started = asyncio.Event()

        async def blocked():
            started.set()
            await asyncio.Event().wait()

        self.client.connect = blocked
        task = asyncio.create_task(self.app.dispatch("connect tcp localhost"))
        await started.wait()
        await asyncio.wait_for(self.app.dispatch("cancel"), 1)
        with self.assertRaises(CommandError):
            await task
        self.assertIsNone(self.app.connection.client)

    async def test_shutdown_cancels_io(self):
        await self.connect()
        self.client.gate = asyncio.Event()
        task = asyncio.create_task(self.app.dispatch("read coils 0"))
        await self.client.started.wait()
        await asyncio.wait_for(self.app.on_stop(), 1)
        with self.assertRaises(CommandError):
            await task
        self.assertFalse(self.client.connected)

    async def test_failed_connect_cleanup(self):
        self.client.connect = AsyncMock(return_value=False)
        with self.assertRaises(CommandError):
            await self.connect()
        self.assertIsNone(self.app.connection.client)
        self.assertFalse(self.client.connected)

    async def test_double_connect_rejected(self):
        await self.connect()
        with self.assertRaisesRegex(CommandError, "already open"):
            await self.connect()

    async def test_disconnected_session(self):
        await self.connect()
        self.client.connected = False
        with self.assertRaisesRegex(CommandError, "disconnected"):
            await self.app.dispatch("read coils 0")

    async def test_profiles_records_history_and_project_isolation(self):
        await self.connect()
        await self.app.dispatch("profile save lab")
        await self.app.dispatch("read coils 0")
        self.assertEqual((await self.app.configs.get("lab"))["unit"], 7)
        self.assertEqual(len(await self.app.records.query()), 2)
        for text in (
            "project create new",
            "proj lo default",
            "project reset records confirm",
        ):
            with self.assertRaises(CommandError):
                await self.app.dispatch(text)
        await self.app.dispatch("close")
        await self.app.dispatch("project create new")
        self.assertNotIn("lab", await self.app.configs.list())
        self.assertEqual(await self.app.records.query(), [])
        await self.app.dispatch("project load default")
        await self.app.dispatch("profile connect lab")
        self.assertEqual(self.app.connection.settings.unit, 7)
        history = await self.app.history.all()
        self.assertIn("read coils 0", [entry.command for entry in history])

    async def test_no_io_during_recording_session_start(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.app.records.start_session

        async def slow_start(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        with patch.object(self.app.records, "start_session", slow_start):
            task = asyncio.create_task(self.app.dispatch("connect tcp localhost"))
            await entered.wait()
            with self.assertRaisesRegex(CommandError, "opening"):
                await self.app.dispatch("read coils 0")
            with self.assertRaises(CommandError):
                await self.app.dispatch("project create wrong")
            release.set()
            await task
        await self.app.dispatch("read coils 0")
        self.assertEqual(len(await self.app.records.query()), 2)

    async def test_record_warning_preserved_on_protocol_error(self):
        await self.connect()
        self.client.reply = lambda name, args: response(function_code=3, registers=[])
        with patch.object(
            self.app.records, "append", AsyncMock(side_effect=OSError("disk full"))
        ):
            with self.assertRaisesRegex(CommandError, "Recording warning: disk full"):
                await self.app.dispatch("read holding_registers 0")

    async def test_cli_command_file_and_argument_failure(self):
        from pathlib import Path

        with tempfile.TemporaryDirectory() as path:
            script = Path(path) / "commands.txt"
            script.write_text(
                "# local fixture\n\nconnect tcp localhost\nread coils 0\n",
                encoding="utf-8",
            )
            app = ModbusApp(
                data_dir=Path(path) / "data",
                client_factory=lambda settings: self.client,
            )
            out, err = io.StringIO(), io.StringIO()
            status = await app.run_cli(
                ["-f", str(script), "-c", "write coils 0 1"], stdout=out, stderr=err
            )
            self.assertEqual(status, 0, err.getvalue())
            self.assertIn("Write acknowledged", out.getvalue())
            status = await app.run_cli(
                ["-c", "connect tcp localhost", "-c", "write coils 0 nope"],
                stdout=out,
                stderr=err,
            )
            self.assertEqual(status, 2)
            self.assertFalse(self.client.connected)

    async def test_external_cancellation_then_project_change(self):
        await self.connect()
        self.client.gate = asyncio.Event()
        task = asyncio.create_task(self.app.dispatch("read coils 0"))
        await self.client.started.wait()
        task.cancel()
        with self.assertRaises(CommandError):
            await task
        await self.app.dispatch("project create after-external-cancel")
        self.assertIsNone(self.app._record_session)
        self.assertEqual(await self.app.records.query(), [])

    async def test_invalid_profile(self):
        await self.app.configs.save(
            "bad", {"transport": "tcp", "target": "localhost", "timeout": "oops"}
        )
        with self.assertRaises(CommandError):
            await self.app.dispatch("profile connect bad")

    async def test_record_failure_keeps_acknowledged_write(self):
        await self.connect()
        with patch.object(
            self.app.records, "append", AsyncMock(side_effect=OSError("disk full"))
        ):
            result = await self.app.dispatch("write coils 0 1")
        self.assertIn("Write acknowledged", result.output)
        self.assertIn("Recording warning: disk full", result.output)
        self.assertEqual(len(self.client.calls), 1)

    async def test_cli_sequence_and_cleanup(self):
        # run_cli owns backend lifecycle; use another app and directory.
        with tempfile.TemporaryDirectory() as path:
            app = ModbusApp(data_dir=path, client_factory=lambda settings: self.client)
            out, err = io.StringIO(), io.StringIO()
            status = await app.run_cli(
                [
                    "-c",
                    "connect tcp localhost",
                    "-c",
                    "read coils 0",
                    "-c",
                    "write coils 0 1",
                ],
                stdout=out,
                stderr=err,
            )
            self.assertEqual(status, 0, err.getvalue())
            self.assertIn("Write acknowledged", out.getvalue())
            self.assertFalse(self.client.connected)
            status = await app.run_cli(["-c", "read coils 0"], stdout=out, stderr=err)
            self.assertEqual(status, 2)


class ValidationTests(unittest.TestCase):
    def test_range_endpoints_and_order(self):
        spans = list(read_chunks(IntegerRanges("65535,0-2,1"), 2, 125))
        self.assertEqual(
            [(x.start, x.count, x.stop) for x in spans],
            [(65535, 1, 65536), (0, 2, 2), (2, 1, 3), (1, 1, 2)],
        )

    def test_invalid_connection_settings(self):
        for kwargs in (
            {"unit": 0},
            {"unit": 248},
            {"port": 0},
            {"timeout": float("nan")},
            {"timeout": float("inf")},
            {"timeout": -1},
            {"retries": -1},
            {"parity": "X"},
            {"baudrate": 0},
            {"bytesize": 9},
            {"stopbits": 3},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(CommandError):
                ConnectionSettings("tcp", "host", **kwargs)

    def test_safe_formatting(self):
        self.assertNotIn("\x1b", format_values("holding_registers", [(0, 27)]))
        self.assertIn("0-1", format_values("coils", [(0, 1), (1, 1), (3, 1)]))
        self.assertIn("ObjectID 200", format_identification({200: b"\xff"}))
