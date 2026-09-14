"""Actual TCP, UDP, RTU and ASCII exchanges against a local PyModbus server."""

import asyncio
import os
import tempfile
import unittest

from ctui import CommandError
from server import make_server

from ctmodbus.app import ModbusApp


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, app):
        for text in (
            "read coils 0-9",
            "read discrete_inputs 0-9",
            "read input_registers 0-129",
            "read holding_registers 0-129",
            "write coils 1 1",
            "write coils 2 0,1,0",
            "write holding_registers 1 65535",
            "write holding_registers 2 0,123,65535",
            "read id",
        ):
            result = await app.dispatch(text)
            self.assertTrue(result.output)
        result = await app.dispatch("read holding_registers 1-4")
        self.assertIn("65535", result.output)
        result = await app.dispatch("read coils 1-4")
        self.assertIn("Bit", result.output)
        with self.assertRaises(CommandError):
            await app.dispatch("read holding_registers 1000")

    async def run_network(self, transport):
        server = make_server(transport)
        await server.serve_forever(background=True)
        if transport == "tcp":
            port = server.transport.sockets[0].getsockname()[1]
        else:
            port = server.transport.get_extra_info("sockname")[1]
        try:
            with tempfile.TemporaryDirectory() as path:
                app = ModbusApp(data_dir=path)
                await app.backend.open()
                try:
                    await app.dispatch(
                        f"connect {transport} 127.0.0.1 --port {port} --timeout 0.5"
                    )
                    await self.exercise(app)
                finally:
                    await app.on_stop()
                    await app.backend.close()
        finally:
            await server.shutdown()

    async def test_tcp(self):
        await self.run_network("tcp")

    async def test_udp(self):
        await self.run_network("udp")

    async def run_serial(self, transport):
        # Two PTYs bridged at their masters exercise the real serial clients and
        # server, including their framing, without requiring attached hardware.
        import tty

        master1, slave1 = os.openpty()
        master2, slave2 = os.openpty()
        loop = asyncio.get_running_loop()
        tty.setraw(slave1)
        tty.setraw(slave2)
        for fd in (master1, master2):
            os.set_blocking(fd, False)

        def forward(source, destination):
            try:
                data = os.read(source, 65536)
                if data:
                    os.write(destination, data)
            except BlockingIOError:
                pass

        loop.add_reader(master1, forward, master1, master2)
        loop.add_reader(master2, forward, master2, master1)
        server = make_server(transport, os.ttyname(slave1))
        try:
            await server.serve_forever(background=True)
            with tempfile.TemporaryDirectory() as path:
                app = ModbusApp(data_dir=path)
                await app.backend.open()
                try:
                    await app.dispatch(
                        f"connect {transport} {os.ttyname(slave2)} --timeout 1"
                    )
                    await self.exercise(app)
                finally:
                    await app.on_stop()
                    await app.backend.close()
        finally:
            await server.shutdown()
            loop.remove_reader(master1)
            loop.remove_reader(master2)
            for fd in (master1, slave1, master2, slave2):
                os.close(fd)

    @unittest.skipUnless(os.name == "posix", "PTY serial tests require POSIX")
    async def test_rtu(self):
        await self.run_serial("rtu")

    @unittest.skipUnless(os.name == "posix", "PTY serial tests require POSIX")
    async def test_ascii(self):
        await self.run_serial("ascii")
