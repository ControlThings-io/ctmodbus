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
    """Check TLS command/profile settings with the shared fake-client fixture."""

    asyncSetUp = test_commands.CommandTests.asyncSetUp
    asyncTearDown = test_commands.CommandTests.asyncTearDown

    async def test_defaults_and_profile_roundtrip(self):
        """Preserve TLS verification and certificate paths across profile save/connect."""
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
        """Reject a client key supplied without a certificate."""
        with self.assertRaisesRegex(CommandError, "requires cert-file"):
            await self.app.dispatch("connect tls example.com --key-file client.key")

    async def test_tls_opening_guard(self):
        """Prevent device I/O until the TLS recording session has started."""
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.app.records.start_session

        async def delayed(*args, **kwargs):
            """Signal and suspend session startup until the test releases its gate."""
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
    """Exercise real TLS with ephemeral certificates; skip if OpenSSL is unavailable.

    Each case opens temporary storage and a loopback server. These tests cover
    trust and identity, not production certificate provisioning.
    """

    @classmethod
    def setUpClass(cls):
        """Generate a temporary self-signed localhost certificate; OpenSSL errors fail setup."""
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
        """Remove the temporary test certificate and private key."""
        cls.certificates.cleanup()

    async def asyncSetUp(self):
        """Open an isolated project and trusted loopback TLS server on an ephemeral port."""
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
        """Stop the app and TLS server, close storage, and remove temporary project data."""
        await self.app.on_stop()
        await self.app.backend.close()
        await self.server.shutdown()
        self.directory.cleanup()

    async def test_verified_tls_operations(self):
        """Verify the shared protocol workflow over a trusted TLS connection."""
        await self.app.dispatch(
            f'connect tls localhost --port {self.port} --ca-file "{self.cert}"'
        )
        await test_integration.TransportTests.exercise(self, self.app)

    async def test_untrusted_certificate_rejected(self):
        """Reject an untrusted server and clear the failed connection."""
        with self.assertRaises(CommandError):
            await self.app.dispatch(
                f"connect tls localhost --port {self.port} --timeout 0.5"
            )
        self.assertIsNone(self.app.connection.client)

    async def test_hostname_mismatch_rejected(self):
        """Reject a trusted certificate whose hostname does not match the target."""
        with self.assertRaises(CommandError):
            await self.app.dispatch(
                f'connect tls 127.0.0.1 --port {self.port} --ca-file "{self.cert}" --timeout 0.5'
            )
        self.assertIsNone(self.app.connection.client)

    async def test_explicit_insecure_connection(self):
        """Allow protocol I/O only after explicitly disabling certificate verification."""
        await self.app.dispatch(f"connect tls 127.0.0.1 --port {self.port} --insecure")
        result = await self.app.dispatch("read coils 0")
        self.assertIn("Read coils", result.output)

    async def test_missing_certificate_file(self):
        """Reject a missing trust file and leave no open client."""
        with self.assertRaises(CommandError):
            await self.app.dispatch(
                f'connect tls localhost --port {self.port} --ca-file "{self.cert}.missing"'
            )
        self.assertIsNone(self.app.connection.client)

    async def test_client_certificate(self):
        # Require a client identity, using the ephemeral test certificate as
        # both the trust anchor and the client identity for this local fixture.
        """Require and exercise mutual TLS using the local ephemeral identity."""
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
    """Check TLS context defaults and reject invalid profile option combinations."""

    def test_secure_defaults(self):
        """Require certificate trust and hostname checks in a default TLS context."""
        context = tls_context(ConnectionSettings("tls", "localhost", port=802))
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_invalid_profile_options(self):
        """Reject malformed TLS option types and key-only profile settings."""
        for values in ({"insecure": "false"}, {"ca_file": 42}, {"key_file": "key"}):
            with self.subTest(values=values), self.assertRaises(CommandError):
                ConnectionSettings("tls", "localhost", **values)
