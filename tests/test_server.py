"""Server configuration, sparse behavior, real listeners and proxy regressions."""

import asyncio
import copy
import os
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from ctui import CommandError, ConfirmationRequired
from pymodbus import FramerType
from pymodbus.client import (
    AsyncModbusSerialClient,
    AsyncModbusTcpClient,
    AsyncModbusTlsClient,
    AsyncModbusUdpClient,
)

from ctmodbus.app import ModbusApp
from ctmodbus.server_config import definition, dumps, load, validate
from ctmodbus.simulation import Simulator
from ctmodbus.tags import Tag, decode_tag_value
from tests.server import make_server


def free_port(udp=False):
    """Reserve a test port candidate; listener binding still checks failures."""
    with socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
    ) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ConfigTests(unittest.TestCase):
    """Validate maps and codecs independently of transport or project storage."""

    def test_full_defaults_and_sparse_roundtrip(self):
        config = definition()
        self.assertEqual(validate(config), config)
        config["tables"]["holding_registers"]["ranges"] = [
            {
                "start": 7,
                "end": 10,
                "mode": "sequence",
                "values": [1, 2],
                "advance": "time",
                "interval_seconds": 0.5,
            }
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "device.toml"
            path.write_text(dumps(config))
            self.assertEqual(load(path), config)
        sparse = validate(
            {
                "version": 1,
                "tables": {"coils": {"ranges": [{"start": 7, "value": True}]}},
            }
        )
        self.assertEqual(sparse["tables"]["holding_registers"]["unmapped"], "illegal")

    def test_invalid_spans_and_rules(self):
        for rule in (
            {"start": 65536, "value": 0},
            {"start": 7, "mode": "random", "min": 8, "max": 4},
            {"start": 7, "mode": "sequence", "values": []},
            {
                "start": 7,
                "mode": "sequence",
                "values": [1],
                "advance": "time",
                "interval_seconds": 0,
            },
        ):
            with self.subTest(rule=rule), self.assertRaises(CommandError):
                validate({"tables": {"holding_registers": {"ranges": [rule]}}})
        with self.assertRaises(CommandError):
            validate(
                {
                    "tags": {
                        "bad": {
                            "table": "holding_registers",
                            "address": 65535,
                            "type": "float32",
                            "value": 1.0,
                        }
                    }
                }
            )


class SimulationTests(unittest.IsolatedAsyncioTestCase):
    """Exercise transaction rollback, coherent tags and dynamic state advancement."""

    async def test_sparse_defaults_and_writes(self):
        sim = Simulator(definition())
        self.assertEqual(await sim.access("holding_registers", 65535, 1), [0])
        self.assertEqual(sim.values, {})
        await sim.access("holding_registers", 65535, 1, [42])
        self.assertEqual(await sim.access("holding_registers", 65535, 1), [42])
        self.assertEqual(len(sim.values), 1)

    async def test_typed_sequences_and_partial_reads(self):
        config = definition(False)
        config["tags"]["level"] = dict(
            table="input_registers",
            address=10,
            type="float32",
            mode="sequence",
            values=[12.5, 99.0],
        )
        sim = Simulator(config)
        tag = Tag("level", "input_registers", 10, "float32")
        self.assertEqual(
            decode_tag_value(tag, await sim.access("input_registers", 10, 2)), 12.5
        )
        self.assertEqual(
            decode_tag_value(tag, await sim.access("input_registers", 10, 2)), 99.0
        )
        self.assertEqual(len(await sim.access("input_registers", 11, 1)), 1)
        with self.assertRaises(CommandError):
            await sim.access("input_registers", 9, 2)

    async def test_hooks_commit_and_roll_back(self):
        config = definition(False)
        config["tags"] = {
            "enable": dict(table="coils", address=0, type="bool", value=False),
            "running": dict(
                table="discrete_inputs", address=0, type="bool", value=False
            ),
        }

        def hook(device, name, value):
            device.set("running", value)

        sim = Simulator(config, {"on_write": hook})
        await sim.access("coils", 0, 1, [True])
        self.assertEqual(await sim.access("discrete_inputs", 0, 1), [1])

        def failing(device, name, value):
            device.set("running", value)
            raise ValueError("broken hook")

        sim.hooks["on_write"] = failing
        with self.assertRaises(ValueError):
            await sim.access("coils", 0, 1, [False])
        self.assertEqual(await sim.access("coils", 0, 1), [1])
        self.assertEqual(await sim.access("discrete_inputs", 0, 1), [1])

    async def test_timed_sequences_and_seed(self):
        now = [0.0]
        config = definition(False)
        config["tables"]["holding_registers"]["ranges"] = [
            dict(
                start=7,
                end=7,
                mode="sequence",
                values=[10, 20, 30],
                advance="time",
                interval_seconds=0.5,
                repeat=False,
            )
        ]
        sim = Simulator(config, clock=lambda: now[0])
        self.assertEqual(await sim.access("holding_registers", 7, 1), [10])
        now[0] = 5
        self.assertEqual(await sim.access("holding_registers", 7, 1), [30])
        config["seed"] = 123
        config["tables"]["holding_registers"]["ranges"] = [
            dict(start=7, end=7, mode="random", min=1, max=100)
        ]
        first, second = Simulator(config), Simulator(config)
        self.assertEqual(
            [await first.access("holding_registers", 7, 1) for _ in range(5)],
            [await second.access("holding_registers", 7, 1) for _ in range(5)],
        )


class ServerTests(unittest.IsolatedAsyncioTestCase):
    """Use actual TCP/UDP clients and upstream servers; no external network traffic."""

    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.app = ModbusApp(data_dir=self.folder.name)
        await self.app.backend.open()
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            client.close()
        await self.app.on_stop()
        await self.app.backend.close()
        self.folder.cleanup()

    async def client(self, transport="tcp"):
        port = free_port(transport == "udp")
        await self.app.dispatch(f"serve {transport} 127.0.0.1 --port {port}")
        cls = AsyncModbusTcpClient if transport == "tcp" else AsyncModbusUdpClient
        client = cls("127.0.0.1", port=port, timeout=0.5, retries=0)
        self.clients.append(client)
        self.assertTrue(await client.connect())
        return client

    async def test_tcp_and_udp_boundaries_and_identity(self):
        for transport in ("tcp", "udp"):
            client = await self.client(transport)
            for method in (
                "read_coils",
                "read_discrete_inputs",
                "read_holding_registers",
                "read_input_registers",
            ):
                result = await getattr(client, method)(65535, count=1, device_id=1)
                self.assertFalse(result.isError())
            result = await client.read_holding_registers(65535, count=2, device_id=1)
            self.assertEqual(result.exception_code, 2)
            result = await client.write_register(65535, 42, device_id=1)
            self.assertFalse(result.isError())
            self.assertEqual(
                (
                    await client.read_holding_registers(65535, count=1, device_id=1)
                ).registers,
                [42],
            )
            result = await client.read_device_information(device_id=1)
            self.assertEqual(result.information[0], b"ControlThings")
            await self.app.dispatch("serve stop")

    async def test_ui_configuration_export_and_import_confirmation(self):
        for text in (
            "serve data clear --confirm",
            "tag create level input_register 10 float32",
            "serve data set tag level 12.5",
            "serve data set holding_registers 100-199 42",
            "serve data sequence holding_registers 7 10,20,30 --advance read",
            "serve data table coils --unmapped default --default true",
        ):
            await self.app.dispatch(text)
        path = Path(self.folder.name) / "device.toml"
        await self.app.dispatch(f"serve data export {path}")
        original = await self.app.server_definition()
        await self.app.dispatch("serve data clear --confirm")
        await self.app.dispatch(f"serve data import {path}")
        self.assertEqual(await self.app.server_definition(), original)
        changed = copy.deepcopy(original)
        changed["tags"]["level"]["address"] = 20
        path.write_text(dumps(changed))
        with self.assertRaises(ConfirmationRequired):
            await self.app.dispatch(f"serve data import {path}")

        async def approve(message):
            path.write_text(dumps(definition(False)))
            with self.assertRaises(CommandError):
                await self.app.dispatch("project create other")
            return True

        await self.app.dispatch(f"serve data import {path}", confirm_callback=approve)
        self.assertEqual((await self.app.tags.get("level")).address, 20)
        self.assertEqual(
            (await self.app.server_definition())["tags"]["level"]["address"], 20
        )

    async def test_sparse_map_dynamic_rules_and_lifecycle_guards(self):
        await self.app.dispatch("serve data clear --confirm")
        await self.app.dispatch(
            "serve data sequence holding_registers 7 10,20 --advance read"
        )
        client = await self.client()
        self.assertEqual(
            (await client.read_holding_registers(7, count=1, device_id=1)).registers,
            [10],
        )
        self.assertEqual(
            (await client.read_holding_registers(7, count=1, device_id=1)).registers,
            [20],
        )
        self.assertEqual(
            (
                await client.read_holding_registers(8, count=1, device_id=1)
            ).exception_code,
            2,
        )
        for text in (
            "project create other",
            "serve data clear --confirm",
            "tag create x coil 0 bool",
        ):
            with self.assertRaises(CommandError):
                await self.app.dispatch(text)
        self.assertIn("7", (await self.app.dispatch("serve data show")).output)
        await self.app.dispatch("serve data reset --confirm")
        self.assertEqual(
            (await client.read_holding_registers(7, count=1, device_id=1)).registers,
            [10],
        )

    async def test_proxy_tcp_to_udp_and_client_observations(self):
        upstream = make_server("udp")
        await upstream.serve_forever(background=True)
        port = upstream.transport.get_extra_info("sockname")[1]
        try:
            await self.app.dispatch(f"connect udp 127.0.0.1 --port {port}")
            await self.app.dispatch("read holding_registers 0")
            self.assertIn("17", (await self.app.dispatch("connect data show")).output)
            await self.app.dispatch("serve data clear --confirm")
            await self.app.dispatch("serve data unit 7")
            client = await self.client()
            await self.app.dispatch("proxy enable")
            self.assertEqual(
                (
                    await client.read_holding_registers(0, count=1, device_id=7)
                ).registers,
                [17],
            )
            self.assertEqual(
                (
                    await client.read_holding_registers(1000, count=1, device_id=7)
                ).exception_code,
                2,
            )
            self.assertFalse(
                (await client.write_register(0, 55, device_id=7)).isError()
            )
            self.assertEqual(
                (
                    await client.read_holding_registers(0, count=1, device_id=7)
                ).registers,
                [55],
            )
            for text in ("serve data show", "connect data show"):
                self.assertIn("55", (await self.app.dispatch(text)).output)
            await self.app.dispatch("proxy disable")
            self.assertEqual(
                (
                    await client.read_holding_registers(0, count=1, device_id=7)
                ).exception_code,
                2,
            )
            await self.app.dispatch("serve stop")
            self.assertTrue(self.app.connection.connected)
        finally:
            await upstream.shutdown()

    async def test_proxy_failure_never_falls_back_and_state_views_differ(self):
        upstream = make_server("tcp")
        await upstream.serve_forever(background=True)
        port = upstream.transport.sockets[0].getsockname()[1]
        try:
            await self.app.dispatch(f"connect tcp 127.0.0.1 --port {port}")
            client = await self.client()
            await self.app.dispatch("proxy enable")

            async def change(response):
                response.registers = [80]
                return response

            self.app.server.after_response = change
            result = await client.read_holding_registers(0, count=1, device_id=1)
            self.assertEqual(result.registers, [80])
            self.assertEqual(
                self.app.client_state.rows["holding_registers", 0]["read"], 17
            )
            self.assertEqual(
                self.app.server.state.rows["holding_registers", 0]["read"], 80
            )
            await self.app.dispatch("close")
            self.assertEqual(
                (
                    await client.read_holding_registers(0, count=1, device_id=1)
                ).exception_code,
                11,
            )
        finally:
            await upstream.shutdown()

    async def test_hook_file_failure_rolls_back_and_tick_changes_values(self):
        path = Path(self.folder.name) / "logic.py"
        path.write_text(
            "def on_write(device, tag, value):\n    device.set('running', value)\n    raise ValueError('intentional failure')\n\ndef on_tick(device, elapsed):\n    device.set('running', True)\n"
        )
        await self.app.dispatch("serve data clear --confirm")
        await self.app.dispatch("tag create enable coil 0 bool")
        await self.app.dispatch("tag create running discrete_input 0 bool")
        await self.app.dispatch("serve data set tag enable false")
        await self.app.dispatch("serve data set tag running false")
        await self.app.dispatch(f"serve hook write {path} on_write")
        await self.app.dispatch(f"serve hook tick {path} on_tick --interval 0.02")
        await self.app.dispatch("serve data validate")
        client = await self.client()
        response = await client.write_coil(0, True, device_id=1)
        self.assertEqual(response.exception_code, 4)
        self.assertFalse((await client.read_coils(0, count=1, device_id=1)).bits[0])
        self.assertIn(
            "intentional failure", (await self.app.dispatch("serve status")).output
        )

        async def tick_done():
            while not self.app.server.simulator.values.get(
                ("discrete_inputs", 0), False
            ):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(tick_done(), 1)
        self.assertTrue(
            (await client.read_discrete_inputs(0, count=1, device_id=1)).bits[0]
        )
        path_export = Path(self.folder.name) / "exported.toml"
        await self.app.dispatch(f"serve data export {path_export}")
        self.assertEqual(load(path_export)["hooks"]["module"], str(path))

    async def test_raw_invalid_count_and_pipelined_transactions(self):
        await self.client()
        port = self.app.server.listener.transport.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        def frame(transaction, count):
            return struct.pack(">HHHBBHH", transaction, 0, 6, 1, 3, 0, count)

        writer.write(frame(41, 0) + frame(42, 1))
        await writer.drain()

        async def packet():
            header = await reader.readexactly(7)
            transaction, _, length, _ = struct.unpack(">HHHB", header)
            return transaction, await reader.readexactly(length - 1)

        try:
            first = await asyncio.wait_for(packet(), 1)
            second = await asyncio.wait_for(packet(), 1)
            self.assertEqual(first, (41, bytes([0x83, 3])))
            self.assertEqual(second, (42, bytes([3, 2, 0, 0])))
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_bind_failure_and_foreground_cleanup(self):
        port = free_port()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", port))
            occupied.listen()
            with self.assertRaises(CommandError):
                await self.app.dispatch(f"serve tcp 127.0.0.1 --port {port}")
        self.assertIsNone(self.app.server.listener)
        task = asyncio.create_task(
            self.app.dispatch(f"serve tcp 127.0.0.1 --port {port} --foreground")
        )

        async def started():
            while self.app.server.label == "Stopped":
                await asyncio.sleep(0.01)

        await asyncio.wait_for(started(), 1)
        self.assertFalse(task.done())
        await self.app.dispatch("serve stop")
        await asyncio.wait_for(task, 1)
        self.assertIsNone(self.app.server.listener)

    @unittest.skipUnless(shutil.which("openssl"), "TLS certificates require OpenSSL")
    async def test_native_tls_and_client_certificate_requirement(self):
        cert, key = (
            Path(self.folder.name) / "server.pem",
            Path(self.folder.name) / "server.key",
        )
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            check=True,
            capture_output=True,
        )
        port = free_port()
        await self.app.dispatch(
            f"serve tls 127.0.0.1 --port {port} --cert-file {cert} --key-file {key}"
        )
        context = ssl.create_default_context(cafile=str(cert))
        client = AsyncModbusTlsClient(
            "localhost", port=port, sslctx=context, timeout=0.5, retries=0
        )
        self.clients.append(client)
        self.assertTrue(await client.connect())
        self.assertEqual(
            (await client.read_holding_registers(0, count=1, device_id=1)).registers,
            [0],
        )
        client.close()
        await self.app.dispatch("serve stop")
        await self.app.dispatch(
            f"serve tls 127.0.0.1 --port {port} --cert-file {cert} --key-file {key} --ca-file {cert}"
        )
        context.load_cert_chain(str(cert), str(key))
        client = AsyncModbusTlsClient(
            "localhost", port=port, sslctx=context, timeout=0.5, retries=0
        )
        self.clients.append(client)
        self.assertTrue(await client.connect())
        self.assertFalse((await client.read_coils(0, count=1, device_id=1)).isError())

    @unittest.skipUnless(os.name == "posix", "Serial PTYs require POSIX")
    async def test_serial_listeners_and_tcp_to_rtu_proxy(self):
        import tty

        for transport in ("rtu", "ascii"):
            first, a, second, b = (*os.openpty(), *os.openpty())
            loop = asyncio.get_running_loop()
            for fd in (a, b):
                tty.setraw(fd)
            for fd in (first, second):
                os.set_blocking(fd, False)

            def forward(source, destination):
                try:
                    data = os.read(source, 65536)
                    if data:
                        os.write(destination, data)
                except BlockingIOError:
                    pass

            loop.add_reader(first, forward, first, second)
            loop.add_reader(second, forward, second, first)
            peer = None
            try:
                await self.app.dispatch(f"serve {transport} {os.ttyname(a)}")
                peer = AsyncModbusSerialClient(
                    os.ttyname(b),
                    framer=FramerType.RTU if transport == "rtu" else FramerType.ASCII,
                    baudrate=9600,
                    timeout=1,
                    retries=0,
                )
                self.assertTrue(await peer.connect())
                self.assertFalse(
                    (await peer.write_register(65535, 42, device_id=1)).isError()
                )
                self.assertEqual(
                    (
                        await peer.read_holding_registers(65535, count=1, device_id=1)
                    ).registers,
                    [42],
                )
                peer.close()
                peer = None
                # Turn the serial peer into an upstream device and proxy TCP to it.
                await self.app.dispatch("serve stop")
                upstream = make_server(transport, os.ttyname(a))
                await upstream.serve_forever(background=True)
                try:
                    await self.app.dispatch(
                        f"connect {transport} {os.ttyname(b)} --timeout 1"
                    )
                    downstream = await self.client()
                    await self.app.dispatch("proxy enable")
                    self.assertEqual(
                        (
                            await downstream.read_holding_registers(
                                0, count=1, device_id=1
                            )
                        ).registers,
                        [17],
                    )
                    await self.app.dispatch("serve stop")
                    await self.app.dispatch("close")
                finally:
                    await upstream.shutdown()
            finally:
                if peer:
                    peer.close()
                await self.app.server.stop()
                loop.remove_reader(first)
                loop.remove_reader(second)
                for fd in (first, a, second, b):
                    os.close(fd)

    async def test_client_state_session_reset_and_write_evidence(self):
        client = await self.client()
        port = self.app.server.listener.transport.sockets[0].getsockname()[1]
        await self.app.dispatch(f"connect tcp 127.0.0.1 --port {port}")
        await self.app.dispatch("write holding_registers 3 42")
        row = self.app.client_state.rows["holding_registers", 3]
        self.assertNotIn("read", row)
        self.assertIn("acknowledged", row["outcome"])
        await self.app.dispatch("read holding_registers 3")
        self.assertEqual(row["read"], 42)
        await self.app.dispatch("close")
        await self.app.dispatch(f"connect tcp 127.0.0.1 --port {port}")
        self.assertEqual(self.app.client_state.rows, {})
        await self.app.dispatch("close")
        with self.assertRaises(CommandError):
            await self.app.dispatch("write holding_registers 3 99")
        self.assertEqual(
            self.app.client_state.rows["holding_registers", 3]["outcome"], "not sent"
        )
        client.close()
