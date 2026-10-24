"""Bulk and referenced tag deletion, approval guards, and transactional rollback."""

import asyncio
import copy
import io
import unittest
from unittest.mock import AsyncMock, patch

import test_tags
from ctui import CommandError, ConfirmationRequired

from ctmodbus.server_config import CONFIG_NAME, definition


class TagDeletionTests(unittest.IsolatedAsyncioTestCase):
    """Use a real temporary project database with shared tag command fixtures."""

    asyncSetUp = test_tags.TagCommandTests.asyncSetUp
    asyncTearDown = test_tags.TagCommandTests.asyncTearDown

    async def seed(self, hooks=False):
        """Create two project tags and one associated server tag rule."""
        await self.app.dispatch("tags create timer holding_register 2 uint16")
        await self.app.dispatch("tags create ready coil 0 bool")
        config = definition()
        config["seed"] = 9
        config["tags"]["timer"] = {
            "table": "holding_registers",
            "address": 2,
            "type": "uint16",
            "mode": "sequence",
            "values": [1, 2],
        }
        config["tables"]["holding_registers"]["ranges"] = [
            {"start": 8, "end": 9, "value": 55}
        ]
        if hooks:
            config["hooks"] = {"module": "unused.py", "on_read": "read"}
        await self.app.save_server_definition(config)
        return await self.app.server_definition()

    async def test_bulk_requires_approval_and_empty_is_noop(self):
        """Empty projects do not prompt; malformed and unknown selections fail safely."""
        self.assertEqual(
            (await self.app.dispatch("tags delete --all")).output, "No tags to delete."
        )
        await self.app.dispatch("tags create timer holding_register 2 uint16")
        for command in (
            "tags delete",
            "tags delete timer --all",
            "tags delete unknown",
        ):
            with self.assertRaises(CommandError):
                await self.app.dispatch(command)
        with self.assertRaisesRegex(ConfirmationRequired, "Delete 1 project tags"):
            await self.app.dispatch("tags delete --all")
        declined = await self.app.dispatch(
            "tags delete --all", confirm_callback=lambda message: False
        )
        self.assertFalse(declined.accepted)
        self.assertEqual(await self.app.tags.names(), {"timer"})
        result = await self.app.dispatch("tags delete --all --confirm")
        self.assertIn("Deleted 1", result.output)
        self.assertEqual(await self.app.tags.names(), set())
        self.assertNotIn(CONFIG_NAME, await self.app.configs.list())

    async def test_references_require_opt_in_and_unrelated_state_is_retained(self):
        """Single and bulk deletion refuse saved references without explicit rule removal."""
        config = await self.seed()
        for command in ("tags delete timer", "tags delete --all --confirm"):
            with self.assertRaisesRegex(CommandError, "timer.*--remove-server-rules"):
                await self.app.dispatch(command)
        self.assertEqual(await self.app.server_definition(), config)
        await self.app.dispatch("tags delete ready")
        self.assertEqual(await self.app.tags.names(), {"timer"})
        with self.assertRaises(ConfirmationRequired):
            await self.app.dispatch("tags delete timer --remove-server-rules")
        await self.app.dispatch("tags delete timer --remove-server-rules --confirm")
        config["tags"] = {}
        self.assertEqual(await self.app.server_definition(), config)
        self.assertEqual(await self.app.tags.names(), set())

    async def test_confirmed_exact_plan_and_hooks_warning(self):
        """Show both counts and hook warning before approval, blocking competing edits."""
        config = await self.seed(hooks=True)

        async def approve(message):
            self.assertIn(
                "Delete 2 project tags and remove 1 server tag rules", message
            )
            self.assertIn("Python hooks", message)
            for command in (
                "tags create another coil 3 bool",
                "tags rename timer renamed",
                "tags delete ready",
                "tags import missing.toml",
                "project create other",
                "server config unit 2",
                "server start tcp localhost",
                "poll tags",
            ):
                with self.assertRaises(CommandError):
                    await self.app.dispatch(command)
            await self.app.dispatch("help tags delete")
            return True

        result = await self.app.dispatch(
            "tags del --all --remove-server-rules", confirm_callback=approve
        )
        self.assertIn("Python hooks", result.output)
        config["tags"] = {}
        self.assertEqual(await self.app.server_definition(), config)
        self.assertEqual(await self.app.tags.names(), set())
        self.assertIsNone(self.app._tag_delete_task)
        self.assertEqual(self.app._prepared_tag_deletions, {})

    async def test_cancellation_during_confirmation_preserves_everything(self):
        """Cancelled approval releases guards without applying any part of deletion."""
        config = await self.seed()
        entered = asyncio.Event()

        async def approve(message):
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            self.app.dispatch(
                "tags delete --all --remove-server-rules", confirm_callback=approve
            )
        )
        await entered.wait()
        task.cancel()
        with self.assertRaisesRegex(CommandError, "cancelled"):
            await task
        self.assertEqual(await self.app.tags.names(), {"timer", "ready"})
        self.assertEqual(await self.app.server_definition(), config)
        self.assertIsNone(self.app._tag_delete_task)
        self.assertEqual(self.app._prepared_tag_deletions, {})

    async def test_sql_failure_rolls_back_tags_and_config(self):
        """A failing config update rolls back all deletes on the separate connection."""
        config = await self.seed()
        await self.app.backend.connection.execute(
            "CREATE TRIGGER reject_config BEFORE UPDATE ON configs BEGIN SELECT RAISE(ABORT, 'blocked'); END"
        )
        await self.app.backend.connection.commit()
        with self.assertRaisesRegex(CommandError, "rolled back"):
            await self.app.dispatch("tags delete --all --remove-server-rules --confirm")
        self.assertEqual(await self.app.tags.names(), {"timer", "ready"})
        self.assertEqual(await self.app.server_definition(), config)

    async def test_later_delete_failure_rolls_back_earlier_deletes(self):
        """A later tag SQL failure cannot expose a partial bulk deletion."""
        await self.seed()
        await self.app.backend.connection.execute(
            "CREATE TRIGGER reject_tag BEFORE DELETE ON tags WHEN OLD.name = 'timer' BEGIN SELECT RAISE(ABORT, 'blocked'); END"
        )
        await self.app.backend.connection.commit()
        before = await self.app.server_definition()
        with self.assertRaisesRegex(CommandError, "rolled back"):
            await self.app.dispatch("tags delete --all --remove-server-rules --confirm")
        self.assertEqual(await self.app.tags.names(), {"timer", "ready"})
        self.assertEqual(await self.app.server_definition(), before)

    async def test_changed_saved_config_cannot_be_overwritten(self):
        """Even an inherited config edit during approval is detected before mutation."""
        config = await self.seed()
        changed = copy.deepcopy(config)
        changed["unit"] = 7

        async def approve(message):
            await self.app.configs.save(CONFIG_NAME, changed)
            return True

        with self.assertRaisesRegex(CommandError, "configuration changed"):
            await self.app.dispatch(
                "tags delete --all --remove-server-rules", confirm_callback=approve
            )
        self.assertEqual(await self.app.tags.names(), {"timer", "ready"})
        self.assertEqual(await self.app.server_definition(), changed)

    async def test_inflight_tag_edit_prevents_deletion(self):
        """Do not prepare deletion while an earlier create is unfinished."""
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.app.tags.save

        async def paused(tag):
            entered.set()
            await release.wait()
            await original(tag)

        with patch.object(self.app.tags, "save", paused):
            task = asyncio.create_task(
                self.app.dispatch("tags create ready coil 0 bool")
            )
            await entered.wait()
            try:
                with self.assertRaisesRegex(CommandError, "Tag edits"):
                    await self.app.dispatch("tags delete --all --confirm")
            finally:
                release.set()
                await task
        self.assertEqual(await self.app.tags.names(), {"ready"})

    async def test_server_and_polling_must_be_stopped(self):
        """Existing lifecycle guards also cover confirmed bulk deletion."""
        await self.seed()
        with patch.object(self.app.server, "listener", object()):
            with self.assertRaisesRegex(CommandError, "Stop the server"):
                await self.app.dispatch(
                    "tags delete --all --remove-server-rules --confirm"
                )
        await self.app.dispatch("client start tcp localhost")
        await self.app.dispatch("poll raw --coils 0 --interval 0.01")
        try:
            with self.assertRaisesRegex(CommandError, "Stop polling"):
                await self.app.dispatch(
                    "tags delete --all --remove-server-rules --confirm"
                )
        finally:
            await self.app.dispatch("poll stop")
        self.assertEqual(await self.app.tags.names(), {"timer", "ready"})

    async def test_browser_confirmation_then_message_result(self):
        """The real WUI presenter asks Yes/No and presents completion as a message."""
        from ctui.web import WebClient, WebSession

        await self.seed()
        session = WebSession(self.app, port=0, stdout=io.StringIO())
        socket = type("Socket", (), {"closed": False, "send_json": AsyncMock()})()
        view = WebClient(session, socket)
        try:
            await session.start()
            self.app.layout.set_output("Existing output")
            with patch.object(
                view, "dialog", AsyncMock(return_value={"button": 1})
            ) as dialog:
                await view.spawn(
                    view.command("tags delete --all --remove-server-rules", "decline")
                )
                self.assertEqual(dialog.await_args.args[0], "Confirm")
                self.assertEqual(dialog.await_args.args[2], ["Yes", "No"])
            self.assertEqual(await self.app.tags.names(), {"timer", "ready"})
            with patch.object(
                view, "dialog", AsyncMock(return_value={"button": 0})
            ) as dialog:
                await view.spawn(
                    view.command("tags delete --all --remove-server-rules", "approve")
                )
                self.assertEqual(dialog.await_count, 2)
                self.assertEqual(dialog.await_args.args[0], "Tags deleted")
                self.assertEqual(len(dialog.await_args.args[2]), 1)
            self.assertEqual(await self.app.tags.names(), set())
            self.assertEqual(self.app.layout.output_field.text, "Existing output")
        finally:
            await session.close()
