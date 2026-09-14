"""TLS command, trust validation, client identity, and protocol integration."""

import asyncio
import shutil
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_commands
import test_integration
from ctui import CommandError
from pymodbus.server import ModbusTlsServer
from server import device

from ctmodbus.app import ModbusApp
from ctmodbus.connection import ConnectionSettings, tls_context


class TlsOptionsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_commands.CommandTests.asyncSetUp
    asyncTearDown = test_commands.CommandTests.asyncTearDown

    async def test_defaults_and_profile_roundtrip(self):
        await self.app.dispatch("connect tls example.com")
        self.assertEqual(self.app.connection.settings.port, 802)
        self.assertFalse(self.app.connection.settings.insecure)
        await self.app.dispatch("close")
        await self.app.dispatch(
            'connect tls example.com --port 1802 --ca-file "root ca.pem" --cert-file client.pem --key-file client.key --insecure'
        )
        await self.app.dispatch("profile save secure")
        settings = self.app.connection.settings
        await self.app.dispatch("close")
        await self.app.dispatch("profile connect secure")
        self.assertEqual(settings, self.app.connection.settings)
        self.assertIn("TLS example.com:1802", self.app.connection_status())

    async def test_invalid_key_option(self):
        with self.assertRaisesRegex(CommandError, "requires cert-file"):
            await self.app.dispatch("connect tls example.com --key-file client.key")

    async def test_tls_opening_guard(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.app.records.start_session

        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        with patch.object(self.app.records, "start_session", delayed):
            task = asyncio.create_task(self.app.dispatch("connect tls example.com"))
            await entered.wait()
            with self.assertRaisesRegex(CommandError, "opening"):
                await self.app.dispatch("read coils 0")
            release.set()
            await task


@unittest.skipUnless(shutil.which("openssl"), "TLS integration requires openssl")
class TlsIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.certificates = tempfile.TemporaryDirectory()
        cls.cert = Path(cls.certificates.name) / "server.pem"
        cls.key = Path(cls.certificates.name) / "server.key"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(cls.key),
                "-out",
                str(cls.cert),
                "-days",
                "2",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            check=True,
            capture_output=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.certificates.cleanup()

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = ModbusApp(data_dir=self.directory.name)
        await self.app.backend.open()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        self.server = ModbusTlsServer(
            device(), address=("127.0.0.1", 0), sslctx=context
        )
        await self.server.serve_forever(background=True)
        self.port = self.server.transport.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        await self.app.on_stop()
        await self.app.backend.close()
        await self.server.shutdown()
        self.directory.cleanup()

    async def test_verified_tls_operations(self):
        await self.app.dispatch(
            f'connect tls localhost --port {self.port} --ca-file "{self.cert}"'
        )
        await test_integration.TransportTests.exercise(self, self.app)

    async def test_untrusted_certificate_rejected(self):
        with self.assertRaises(CommandError):
            await self.app.dispatch(
                f"connect tls localhost --port {self.port} --timeout 0.5"
            )
        self.assertIsNone(self.app.connection.client)

    async def test_hostname_mismatch_rejected(self):
        with self.assertRaises(CommandError):
            await self.app.dispatch(
                f'connect tls 127.0.0.1 --port {self.port} --ca-file "{self.cert}" --timeout 0.5'
            )
        self.assertIsNone(self.app.connection.client)

    async def test_explicit_insecure_connection(self):
        await self.app.dispatch(f"connect tls 127.0.0.1 --port {self.port} --insecure")
        result = await self.app.dispatch("read coils 0")
        self.assertIn("Read coils", result.output)

    async def test_missing_certificate_file(self):
        with self.assertRaises(CommandError):
            await self.app.dispatch(
                f'connect tls localhost --port {self.port} --ca-file "{self.cert}.missing"'
            )
        self.assertIsNone(self.app.connection.client)

    async def test_client_certificate(self):
        # Require a client identity, using the ephemeral test certificate as
        # both the trust anchor and the client identity for this local fixture.
        await self.server.shutdown()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        context.load_verify_locations(self.cert)
        context.verify_mode = ssl.CERT_REQUIRED
        self.server = ModbusTlsServer(
            device(), address=("127.0.0.1", 0), sslctx=context
        )
        await self.server.serve_forever(background=True)
        port = self.server.transport.sockets[0].getsockname()[1]
        await self.app.dispatch(
            f'connect tls localhost --port {port} --ca-file "{self.cert}" --cert-file "{self.cert}" --key-file "{self.key}"'
        )
        result = await self.app.dispatch("read coils 0")
        self.assertIn("Read coils", result.output)


class TlsContextTests(unittest.TestCase):
    def test_secure_defaults(self):
        context = tls_context(ConnectionSettings("tls", "localhost", port=802))
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_invalid_profile_options(self):
        for values in ({"insecure": "false"}, {"ca_file": 42}, {"key_file": "key"}):
            with self.subTest(values=values), self.assertRaises(CommandError):
                ConnectionSettings("tls", "localhost", **values)
