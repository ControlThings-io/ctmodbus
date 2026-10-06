"""Typed tag persistence, conversion, I/O, and interchange tests."""

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ctui import CommandError, ConfirmationRequired, PathCompleter

from ctmodbus.app import ModbusApp
from ctmodbus.tags import (
    Tag,
    decode_tag_value,
    encode_tag_value,
    export_tag_document,
    parse_tag_value,
)
from tests.test_commands import FakeClient, response


class TagCodecTests(unittest.TestCase):
    """Verify scalar encodings and parser boundaries independently of device I/O."""

    def test_integer_radices_and_byte_word_order(self):
        """Check radix parsing, signed bit patterns, and default/swapped register bytes."""
        tag = Tag("timer", "holding_registers", 2, "int32")
        self.assertEqual(parse_tag_value(tag, "0d33_000"), 33000)
        self.assertEqual(parse_tag_value(tag, "0b1000_0001"), 129)
        self.assertEqual(parse_tag_value(tag, "-0x10"), -16)
        self.assertEqual(parse_tag_value(tag, "0x8000_0000"), -(2**31))
        self.assertEqual(parse_tag_value(tag, "0xFFFF_FFFF"), -1)
        self.assertEqual(
            encode_tag_value(Tag("x", "holding_registers", 0, "uint32"), 0x01020304),
            [0x0304, 0x0102],
        )
        self.assertEqual(
            encode_tag_value(
                Tag(
                    "x",
                    "holding_registers",
                    0,
                    "uint32",
                    byte_order="little",
                ),
                0x01020304,
            ),
            [0x0403, 0x0201],
        )

    def test_eight_bit_padding_and_round_trips(self):
        """Verify zero padding and signed, wide-integer, and floating codec round trips."""
        big = Tag("x", "holding_registers", 0, "uint8")
        little = Tag("x", "holding_registers", 0, "uint8", byte_order="little")
        self.assertEqual(encode_tag_value(big, 0x12), [0x0012])
        self.assertEqual(encode_tag_value(little, 0x12), [0x1200])
        for tag, value in (
            (Tag("x", "holding_registers", 0, "int8"), -2),
            (Tag("x", "holding_registers", 0, "int16"), -1234),
            (Tag("x", "holding_registers", 0, "uint64"), 2**60),
            (Tag("x", "holding_registers", 0, "float32"), 12.5),
            (Tag("x", "holding_registers", 0, "float64"), -3.25e20),
        ):
            with self.subTest(type=tag.type):
                encoded = encode_tag_value(tag, value)
                self.assertEqual(decode_tag_value(tag, encoded), value)

    def test_value_and_definition_validation(self):
        """Reject incompatible tables, invalid spans/names, and non-finite float input."""
        with self.assertRaises(CommandError):
            Tag("bad name", "coils", 0, "bool").validate()
        with self.assertRaises(CommandError):
            Tag("bad", "coils", 0, "uint16").validate()
        with self.assertRaises(CommandError):
            Tag("bad", "holding_registers", 65535, "uint32").validate()
        float_tag = Tag("x", "holding_registers", 0, "float32")
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value), self.assertRaises(CommandError):
                parse_tag_value(float_tag, value)

    def test_empty_export_has_an_importable_tags_table(self):
        """Ensure an empty export includes the required tags table header."""
        self.assertIn("[tags]", export_tag_document([]))


class TagCommandTests(unittest.IsolatedAsyncioTestCase):
    """Exercise tag persistence and commands with isolated storage and fake I/O."""

    async def asyncSetUp(self):
        """Open a fresh temporary project and inject a deterministic fake client."""
        self.directory = tempfile.TemporaryDirectory()
        self.client = FakeClient()
        self.app = ModbusApp(
            data_dir=self.directory.name, client_factory=lambda settings: self.client
        )
        await self.app.backend.open()

    async def asyncTearDown(self):
        """Stop application tasks, close project storage, and remove temporary data."""
        await self.app.on_stop()
        await self.app.backend.close()
        self.directory.cleanup()

    async def connect(self):
        """Open the test TCP session using the injected fake client."""
        await self.app.dispatch("connect tcp localhost")

    async def test_create_list_rename_delete_and_project_scope(self):
        """Verify tag CRUD, project switching, and full-reset removal."""
        await self.app.dispatch("tags create timer holding_register 2 int32")
        result = await self.app.dispatch("tags list")
        self.assertIn("timer", result.output)
        self.assertIn("little", result.output)
        result = await self.app.dispatch("tags show timer")
        self.assertIn("range: 2-3", result.output)
        await self.app.dispatch("tags rename timer duration")
        self.assertEqual((await self.app.tags.get("duration")).address, 2)
        await self.app.dispatch("tags delete duration")
        self.assertEqual(await self.app.tags.list(), [])

        await self.app.dispatch("tags create local coil 0 bool")
        await self.app.dispatch("project create other")
        self.assertEqual(await self.app.tags.list(), [])
        await self.app.dispatch("project load default")
        self.assertEqual((await self.app.tags.get("local")).table, "coils")
        await self.app.dispatch("project reset all confirm")
        self.assertEqual(await self.app.tags.list(), [])

    async def test_overlap_warning_and_duplicate_rejection(self):
        """Permit overlaps but reject duplicate names and invalid creation syntax."""
        await self.app.dispatch("tags create first holding_register 0 uint32")
        result = await self.app.dispatch("tags create second holding_register 1 uint16")
        self.assertIn("overlaps tags: first", result.output)
        with self.assertRaisesRegex(CommandError, "already exists"):
            await self.app.dispatch("tags create first holding_register 3 uint16")
        with self.assertRaisesRegex(CommandError, "do not accept"):
            await self.app.dispatch("tags create bit coil 0 bool --byte-order little")
        with self.assertRaisesRegex(CommandError, "must be one of"):
            await self.app.dispatch("tags create old coils 0 bool")

    async def test_tag_reads_and_writes(self):
        """Verify raw encodings, signed writes, read-only rejection, and read-all dispatch."""
        await self.app.dispatch("tags create switch coil 0 bool")
        await self.app.dispatch("tags create state holding_register 5 uint8")
        await self.app.dispatch("tags create timer holding_register 6 int32")
        await self.app.dispatch("tags create sensed discrete_input 4 bool")
        await self.connect()

        await self.app.dispatch("write tag switch on")
        await self.app.dispatch("write tag state 0b0111_0001")
        await self.app.dispatch("write tag timer 0d33_000")
        self.assertEqual(
            [
                (name, values.get("value", values.get("values")))
                for name, values in self.client.calls[-3:]
            ],
            [
                ("write_coil", True),
                ("write_register", 113),
                ("write_registers", [33000, 0]),
            ],
        )
        with self.assertRaisesRegex(CommandError, "read-only"):
            await self.app.dispatch("write tag sensed 1")
        result = await self.app.dispatch("write tag timer 0x8000_0000")
        self.assertIn("-2147483648", result.output)
        self.assertEqual(self.client.calls[-1][1]["values"], [0, 0x8000])
        result = await self.app.dispatch("write tag timer -- -2_000_000_000")
        self.assertIn("-2000000000", result.output)
        with self.assertRaisesRegex(CommandError, "outside the range"):
            await self.app.dispatch("write tag timer -- -4_000_000_000")

        self.client.calls.clear()
        self.client.reply = lambda name, args: (
            response(function_code=1, bits=[True] * 8)
            if name == "read_coils"
            else (
                response(function_code=2, bits=[False] * 8)
                if name == "read_discrete_inputs"
                else response(
                    function_code=3,
                    registers=[113] if args["address"] == 5 else [33000, 0],
                )
            )
        )
        result = await self.app.dispatch("read tags switch,state,timer")
        self.assertIn("switch", result.output)
        self.assertIn("33000", result.output)
        self.assertEqual(len(self.client.calls), 3)

        self.client.calls.clear()
        result = await self.app.dispatch("read tags")
        for name in ("sensed", "state", "switch", "timer"):
            self.assertIn(name, result.output)
        self.assertEqual(len(self.client.calls), 4)

    async def test_multi_tag_order_duplicates_and_prevalidation(self):
        """Preserve explicit order/repeats and reject unknown tags before I/O."""
        await self.app.dispatch("tags create first holding_register 1 uint16")
        await self.app.dispatch("tags create second holding_register 2 uint16")
        await self.connect()
        await self.app.dispatch("read tags second,first,second")
        self.assertEqual([args["address"] for _, args in self.client.calls], [2, 1, 2])
        self.client.calls.clear()
        with self.assertRaises(CommandError):
            await self.app.dispatch("read tags first,missing")
        self.assertEqual(self.client.calls, [])

    async def test_multi_tag_failure_preserves_completed_rows(self):
        """Keep decoded rows and stop before later tags on a malformed reply."""
        for name, address in (("first", 1), ("second", 2), ("third", 3)):
            await self.app.dispatch(
                f"tags create {name} holding_register {address} uint16"
            )
        await self.connect()
        self.client.reply = lambda name, args: response(
            function_code=3, registers=[42] if args["address"] == 1 else []
        )
        with self.assertRaises(CommandError) as caught:
            await self.app.dispatch("read tags first,second,third")
        output = str(caught.exception)
        for text in (
            "failed at 'second'",
            "1 tags completed",
            "first",
            "42",
            "1 remaining tags",
        ):
            self.assertIn(text, output)
        self.assertEqual(len(self.client.calls), 2)
        self.assertFalse(self.app.connection.lock.locked())
        self.assertTrue(self.app.connection.connected)

    async def test_multi_tag_read_holds_reservation(self):
        """A queued raw read cannot execute between two tag requests."""
        for name, address in (("first", 1), ("second", 2)):
            await self.app.dispatch(
                f"tags create {name} holding_register {address} uint16"
            )
        await self.connect()
        self.client.gate = asyncio.Event()
        tags = asyncio.create_task(self.app.dispatch("read tags first,second"))
        await asyncio.wait_for(self.client.started.wait(), 1)
        competitor = asyncio.create_task(self.app.dispatch("read holding_registers 9"))
        await asyncio.sleep(0)
        self.client.gate.set()
        await asyncio.wait_for(asyncio.gather(tags, competitor), 2)
        self.assertEqual([args["address"] for _, args in self.client.calls], [1, 2, 9])
        self.assertEqual(self.client.peak, 1)

    async def test_multi_tag_cancellation_preserves_completed_rows(self):
        """Cancellation during the second tag retains the first and closes I/O."""
        for name, address in (("first", 1), ("second", 2), ("third", 3)):
            await self.app.dispatch(
                f"tags create {name} holding_register {address} uint16"
            )
        await self.connect()
        second_started = asyncio.Event()

        def reply(name, args):
            """Suspend the next request after the first tag succeeds."""
            self.client.gate = asyncio.Event()
            self.client.started = second_started
            return response(function_code=3, registers=[42])

        self.client.reply = reply
        task = asyncio.create_task(self.app.dispatch("read tags first,second,third"))
        await asyncio.wait_for(second_started.wait(), 1)
        task.cancel()
        with self.assertRaises(CommandError) as caught:
            await asyncio.wait_for(task, 2)
        output = str(caught.exception)
        for text in (
            "cancelled",
            "failed at 'second'",
            "first",
            "42",
            "1 tags completed",
        ):
            self.assertIn(text, output)
        self.assertFalse(self.app.connection.connected)
        self.assertFalse(self.app.connection.lock.locked())
        self.assertEqual(len(self.client.calls), 2)

    async def test_read_all_requires_at_least_one_defined_tag(self):
        """Report an empty tag project before attempting any device read."""
        with self.assertRaisesRegex(CommandError, "No tags are defined"):
            await self.app.dispatch("read tags")

    async def test_export_import_collision_confirmation_and_replace(self):
        """Round-trip TOML and verify collision rejection, declined prompts, and replace."""
        await self.app.dispatch("tags create timer holding_register 2 int32")
        path = Path(self.directory.name) / "my_tags"
        result = await self.app.dispatch(f"tags export {path}")
        exported = path.with_suffix(".toml")
        self.assertTrue(exported.is_file())
        self.assertIn('word_order = "little"', exported.read_text(encoding="utf-8"))
        await self.app.dispatch("tags delete timer")
        await self.app.dispatch(f"tags import {exported}")
        self.assertEqual((await self.app.tags.get("timer")).count, 2)

        with self.assertRaisesRegex(ConfirmationRequired, "timer"):
            await self.app.dispatch(f"tags import {exported}")
        messages = []

        async def decline(message):
            """Capture the confirmation message and return False without changing tags."""
            messages.append(message)
            return False

        result = await self.app.dispatch(
            f"tags import {exported}", confirm_callback=decline
        )
        self.assertFalse(result.accepted)
        self.assertIn("--replace", messages[0])
        result = await self.app.dispatch(f"tags import {exported} --replace")
        self.assertIn("Imported 1 tags", result.output)

    async def test_import_uses_confirmed_data_and_guards_project(self):
        """A changed file cannot change approved data; prefixes share the guard."""
        await self.app.dispatch("tags create timer holding_register 2 uint16")
        path = Path(self.directory.name) / "confirmed.toml"
        path.write_text(
            export_tag_document([Tag("timer", "holding_registers", 9, "uint16")])
        )

        async def approve(message):
            """Try competing mutations and replace the file before approving."""
            self.assertIn("timer", message)
            for command in (
                "project create other",
                "tags delete timer",
                "tags import missing.toml",
            ):
                with self.assertRaisesRegex(CommandError, "import is in progress"):
                    await self.app.dispatch(command)
            path.write_text(
                export_tag_document([Tag("unexpected", "coils", 0, "bool")])
            )
            await self.app.dispatch("help tags import")
            return True

        await self.app.dispatch(f"tags imp {path}", confirm_callback=approve)
        self.assertEqual((await self.app.tags.get("timer")).address, 9)
        self.assertEqual(await self.app.tags.names(), {"timer"})
        self.assertIsNone(self.app._tag_import_task)
        self.assertEqual(self.app._prepared_tag_imports, {})
        await self.app.dispatch("project create other")
        self.assertEqual(await self.app.tags.names(), set())

    async def test_import_rejects_an_inflight_tag_edit(self):
        """Do not confirm against tags while an earlier edit is unfinished."""
        started, release = asyncio.Event(), asyncio.Event()
        save = self.app.tags.save

        async def paused_save(tag):
            """Suspend an existing tag creation before saving its row."""
            started.set()
            await release.wait()
            await save(tag)

        with patch.object(self.app.tags, "save", paused_save):
            task = asyncio.create_task(self.app.dispatch("tags create new coil 0 bool"))
            await asyncio.wait_for(started.wait(), 1)
            try:
                with self.assertRaisesRegex(CommandError, "Tag edits are in progress"):
                    await self.app.dispatch("tags import missing.toml")
                with self.assertRaises(CommandError):
                    await self.app.dispatch("project create other")
            finally:
                release.set()
                await task
        self.assertEqual(await self.app.tags.names(), {"new"})

    async def test_cancelled_import_confirmation_leaves_tags_unchanged(self):
        """Cancellation releases the project guard without applying any data."""
        await self.app.dispatch("tags create timer holding_register 2 uint16")
        path = Path(self.directory.name) / "cancelled.toml"
        path.write_text(
            export_tag_document([Tag("timer", "holding_registers", 9, "uint16")])
        )
        started = asyncio.Event()

        async def approve(message):
            """Wait until the caller cancels the pending confirmation."""
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            self.app.dispatch(f"tags import {path}", confirm_callback=approve)
        )
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaisesRegex(CommandError, "cancelled"):
            await task
        self.assertEqual((await self.app.tags.get("timer")).address, 2)
        self.assertIsNone(self.app._tag_import_task)
        await self.app.dispatch("tags delete timer")

    async def test_import_transaction_rolls_back_every_row(self):
        """A later SQL constraint failure cannot leave earlier inserts committed."""
        await self.app.dispatch("tags create existing coil 0 bool")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.app.tags.import_all(
                [Tag("new", "coils", 1, "bool"), Tag("existing", "coils", 2, "bool")]
            )
        # A framework commit afterward must not expose a partial import.
        await self.app.backend.touch()
        self.assertEqual(await self.app.tags.names(), {"existing"})
        self.assertEqual((await self.app.tags.get("existing")).address, 0)

    async def test_cancel_before_import_transaction_writes_nothing(self):
        """Cancelling before the short transaction starts leaves no imported rows."""
        await self.app.tags.ensure()
        started = asyncio.Event()

        async def wait_before_transaction():
            """Expose a cancellation point before any data mutation."""
            started.set()
            await asyncio.Event().wait()

        with patch.object(
            self.app.tags, "ensure", AsyncMock(side_effect=wait_before_transaction)
        ):
            task = asyncio.create_task(
                self.app.tags.import_all([Tag("new", "coils", 0, "bool")])
            )
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(await self.app.tags.names(), set())

    def test_import_and_export_use_path_completion(self):
        """Expose ctui filesystem suggestions on both tag-file path arguments."""
        for name in ("tags import", "tags export"):
            with self.subTest(command=name):
                completer = self.app.commands[name].arguments["path"].completer
                self.assertIsInstance(completer, PathCompleter)

    async def test_import_is_validated_before_changes(self):
        """Ensure one malformed definition prevents every imported tag from being saved."""
        path = Path(self.directory.name) / "bad.toml"
        path.write_text(
            'format = "ctmodbus-tags"\nversion = 1\n'
            '[tags.good]\ntable = "coils"\naddress = 0\ntype = "bool"\n'
            '[tags.bad]\ntable = "holding_registers"\naddress = 65535\n'
            'type = "float64"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CommandError, "Invalid tag 'bad'"):
            await self.app.dispatch(f"tags import {path}")
        self.assertEqual(await self.app.tags.list(), [])
