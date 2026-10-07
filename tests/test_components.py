"""Component command contracts, lifecycle approval, strict formats, and help."""

import asyncio
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_commands
from ctui import CommandError, ConfirmationRequired
from ctui.commands import _HelpResult
from test_commands import FakeClient

from ctmodbus.app import ModbusApp
from ctmodbus.client_commands import complete_profiles
from ctmodbus.component_help import OVERVIEWS
from ctmodbus.server_config import definition, dumps, load, validate
from ctmodbus.tags import parse_tag_document


class ComponentTests(unittest.IsolatedAsyncioTestCase):
    """Check selected settings and stop approval through shared dispatch."""

    asyncSetUp = test_commands.CommandTests.asyncSetUp
    asyncTearDown = test_commands.CommandTests.asyncTearDown

    async def test_selection_save_load_start_and_project_isolation(self):
        """Configuration editing and load issue no I/O; stop retains selection."""
        await self.app.dispatch(
            "client config set --transport tcp --target localhost --unit 7"
        )
        self.assertFalse(self.client.connected)
        await self.app.dispatch("client config save lab")
        self.assertIn(
            "Unsaved changes: no",
            (await self.app.dispatch("client config show")).output,
        )
        await self.app.dispatch("client config set --unit 8")
        self.assertIn(
            "Unsaved changes: yes",
            (await self.app.dispatch("client config show")).output,
        )
        await self.app.dispatch("client config load lab")
        self.assertIsNone(self.app.connection.client)
        await self.app.dispatch("client start")
        self.assertEqual(self.app.connection.settings.unit, 7)
        for text in ("client config set --unit 9", "client config load lab"):
            with self.assertRaisesRegex(CommandError, "Stop the client"):
                await self.app.dispatch(text)
        await self.app.dispatch("read coils 0")
        await self.app.dispatch("client stop")
        self.assertEqual(self.app.selected_client_settings.unit, 7)
        self.assertIn(
            "evidence retained", (await self.app.dispatch("client status")).output
        )
        await self.app.dispatch("project create other")
        self.assertIsNone(self.app.selected_client_settings)
        self.assertIsNone(self.app.client_config_source)

    async def test_set_is_atomic_and_tls_fields_clear_explicitly(self):
        """Invalid edits retain the full selection; TLS defaults and clearing are explicit."""
        with self.assertRaisesRegex(CommandError, "transport"):
            await self.app.dispatch("client config set --target localhost")
        await self.app.dispatch(
            "client config set --transport tls --target localhost --ca-file ca.pem --cert-file cert.pem --key-file key.pem --insecure true"
        )
        initial = self.app.selected_client_settings
        self.assertEqual(initial.port, 802)
        for text in (
            "client config set --unit 0",
            "client config set --transport tcp",
            "client config set --clear-cert-file",
            "client config set --ca-file next.pem --clear-ca-file",
        ):
            with self.assertRaises(CommandError):
                await self.app.dispatch(text)
            self.assertEqual(self.app.selected_client_settings, initial)
        await self.app.dispatch(
            "client config set --transport tcp --clear-ca-file --clear-cert-file --clear-key-file --insecure false --port 502"
        )
        current = self.app.selected_client_settings
        self.assertEqual(current.transport, "tcp")
        self.assertIsNone(current.ca_file)
        self.assertIsNone(current.cert_file)
        self.assertIsNone(current.key_file)
        self.assertFalse(current.insecure)

    async def test_config_load_reserves_selection_and_project(self):
        """Async loads block competing selection, start, stop, and project changes."""
        await self.app.dispatch("client config set --transport tcp --target localhost")
        await self.app.dispatch("client config save lab")
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.app.configs.get

        async def delayed(name):
            entered.set()
            await release.wait()
            return await original(name)

        with patch.object(self.app.configs, "get", delayed):
            task = asyncio.create_task(self.app.dispatch("cl conf lo lab"))
            await entered.wait()
            try:
                for text in (
                    "client start",
                    "client stop",
                    "client config set --unit 8",
                    "project create next",
                ):
                    with self.assertRaisesRegex(
                        CommandError, "configuration is changing"
                    ):
                        await self.app.dispatch(text)
            finally:
                release.set()
                await task
        self.assertIsNone(self.app._client_config_task)

    async def test_proxy_stop_confirmation_and_reservation(self):
        """Decline preserves both endpoints; approval stops only the selected endpoint."""
        await self.app.dispatch("client start tcp localhost")
        # A sentinel listener avoids sockets while exercising real dispatch approval.
        self.app.server.listener = object()
        self.app.server.proxy = True
        with self.assertRaises(ConfirmationRequired):
            await self.app.dispatch("client stop")
        self.assertTrue(self.app.server.proxy)
        self.assertTrue(self.client.connected)
        result = await self.app.dispatch(
            "client stop", confirm_callback=lambda message: False
        )
        self.assertFalse(result.accepted)
        self.assertTrue(self.app.server.proxy)
        entered, release = asyncio.Event(), asyncio.Event()

        async def approve(message):
            self.assertIn("Proxy", message)
            entered.set()
            await release.wait()
            return True

        task = asyncio.create_task(
            self.app.dispatch("cl sto", confirm_callback=approve)
        )
        await entered.wait()
        try:
            for text in (
                "proxy start",
                "proxy stop",
                "client start",
                "server stop",
                "project create next",
            ):
                with self.assertRaisesRegex(CommandError, "component is stopping"):
                    await self.app.dispatch(text)
        finally:
            release.set()
            await task
            self.app.server.listener = None
        self.assertFalse(self.client.connected)
        self.assertFalse(self.app.server.proxy)
        await self.app.dispatch("client start")
        self.app.server.proxy = True
        await self.app.dispatch("server stop --confirm")
        self.assertTrue(self.client.connected)
        self.assertFalse(self.app.server.proxy)

    async def test_overviews_generated_help_and_no_old_commands(self):
        """Bare groups carry popup results; generated references and ctui configs remain."""
        for component, overview in OVERVIEWS.items():
            result = await self.app.dispatch(component)
            self.assertIsInstance(result, _HelpResult)
            self.assertEqual(self.app.format_ui_help(result.target), overview)
            self.assertIn("start", result.output)
            generated = await self.app.dispatch("help " + component)
            self.assertNotEqual(generated.output, overview)
            self.assertIn("status", generated.output)
        for old in (
            "connect",
            "profile",
            "close",
            "cancel",
            "proxy enable",
            "proxy disable",
            "client data show",
            "server data show",
        ):
            with self.assertRaises(CommandError):
                await self.app.dispatch(old)
        self.assertEqual(self.app.commands.resolve("serve")[0].name, "server")
        await self.app.dispatch("configs show tcp-local")
        names = await complete_profiles(type("Context", (), {"app": self.app})())
        self.assertIn("tcp-local", names)
        self.assertNotIn("ctmodbus-server", names)

    async def test_completion_and_component_registration(self):
        """Every moved subcommand stays registered; optional choices complete correctly."""
        command, _ = self.app.commands.resolve("client config set")
        choices = await command.complete("--transport", "", self.app)
        self.assertEqual(
            {item.value for item in choices}, {"tcp", "udp", "tls", "rtu", "ascii"}
        )
        parity = await command.complete("--parity", "", self.app)
        self.assertEqual({item.value for item in parity}, {"N", "E", "O"})
        await self.app.dispatch("client config set --transport tc --target localhost")
        await self.app.dispatch("client config save lab")
        command, _ = self.app.commands.resolve("client config load")
        self.assertIn(
            "lab", {item.value for item in await command.complete("", "", self.app)}
        )
        for component in ("client", "server"):
            for transport in ("tcp", "udp", "tls", "rtu", "ascii"):
                text = f"{component} start {transport}"
                self.assertEqual(self.app.commands.resolve(text)[0].name, text)
        for action in (
            "import",
            "export",
            "clear",
            "unit",
            "seed",
            "identity",
            "table",
            "set",
            "random",
            "sequence",
            "remove",
            "validate",
            "show",
        ):
            text = "server config " + action
            self.assertEqual(self.app.commands.resolve(text)[0].name, text)
        for action in ("read", "write", "tick", "clear"):
            text = "server hook " + action
            self.assertEqual(self.app.commands.resolve(text)[0].name, text)

    async def test_cli_configuration_and_overviews(self):
        """Real CLI selects/loads without I/O and prints overview examples."""
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient()
            app = ModbusApp(data_dir=folder, client_factory=lambda settings: client)
            stdout, stderr = io.StringIO(), io.StringIO()
            status = await app.run_cli(
                [
                    "-c",
                    "client config load tcp-local",
                    "-c",
                    "client config show",
                    "-c",
                    "client",
                    "-c",
                    "server",
                    "-c",
                    "proxy",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(status, 0, stderr.getvalue())
            self.assertFalse(client.connected)
            for overview in OVERVIEWS.values():
                self.assertIn(overview, stdout.getvalue())

    async def test_browser_overviews_and_stop_confirmations(self):
        """Browser presenter opens overview/confirmation dialogs and retains main output."""
        from unittest.mock import AsyncMock

        from ctui.web import WebClient, WebSession

        session = WebSession(self.app, port=0, stdout=io.StringIO())
        socket = type("Socket", (), {"closed": False, "send_json": AsyncMock()})()
        view = WebClient(session, socket)
        try:
            await session.start()
            self.app.layout.set_output("Existing output")
            with patch.object(
                view, "dialog", AsyncMock(return_value={"button": 0})
            ) as dialog:
                for component, overview in OVERVIEWS.items():
                    await view.command(component, component)
                    dialog.assert_awaited_with("Help", overview, ["OK"])
                    self.assertEqual(
                        self.app.layout.output_field.text, "Existing output"
                    )
            await self.app.dispatch("client start tcp localhost")
            self.app.server.proxy = True
            with patch.object(view, "dialog", AsyncMock(return_value={"button": 1})):
                await view.command("client stop", "decline")
            self.assertTrue(self.client.connected)
            self.assertTrue(self.app.server.proxy)
            with patch.object(view, "dialog", AsyncMock(return_value={"button": 0})):
                await view.command("client stop", "approve")
            self.assertFalse(self.client.connected)
            self.assertFalse(self.app.server.proxy)
        finally:
            await session.close()


class StrictFormatTests(unittest.TestCase):
    """Reject malformed markers and nested obsolete/unknown schema fields."""

    def test_server_markers_and_nested_unknown_keys(self):
        """Every persisted definition requires exact markers and rejects unknown fields."""
        for field, value in (
            ("format", None),
            ("format", "ctmodbus-tags"),
            ("version", None),
            ("version", True),
            ("version", 1.0),
            ("version", 2),
        ):
            config = definition()
            if value is None:
                del config[field]
            else:
                config[field] = value
            with (
                self.subTest(field=field, value=value),
                self.assertRaisesRegex(CommandError, field),
            ):
                validate(config)
        for path, key in (
            ((), "typo"),
            (("identity",), "company"),
            (("tables",), "holding_register"),
            (("tables", "coils"), "fallback"),
            (("hooks",), "tick_seconds"),
        ):
            config = definition()
            section = config
            for part in path:
                section = section[part]
            section[key] = 1
            with self.subTest(path=path), self.assertRaisesRegex(CommandError, key):
                validate(config)
        config = definition()
        config["hooks"] = {
            "module": "test.py",
            "on_tick": "tick",
            "tick_interval_seconds": 0.1,
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "server.toml"
            path.write_text(dumps(config))
            loaded = load(path)
            self.assertEqual(loaded["hooks"]["tick_interval_seconds"], 0.1)
        for value in (False, 0, -1, float("inf")):
            bad = copy.deepcopy(config)
            bad["hooks"]["tick_interval_seconds"] = value
            with self.assertRaisesRegex(CommandError, "tick_interval_seconds"):
                validate(bad)

    def test_tag_markers_and_top_level_unknown_keys(self):
        """Tag version booleans/floats and unrelated tables cannot pass validation."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tags.toml"
            for text in (
                'format = "ctmodbus-tags"\nversion = true\n[tags]\n',
                'format = "ctmodbus-tags"\nversion = 1.0\n[tags]\n',
                "version = 1\n[tags]\n",
                'format = "ctmodbus-tags"\n[tags]\n',
                'format = "ctmodbus-tags"\nversion = 1\nextra = 2\n[tags]\n',
            ):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(CommandError):
                    parse_tag_document(path)
