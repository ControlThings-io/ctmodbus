"""Project-scoped typed Modbus tags and portable TOML files.

Pure codecs operate on validated Tag definitions and raw Modbus values.
TagStore persists definitions in the active ctui SQLite project; commands add
CLI validation and shared protocol operations. Names are case-sensitive.
Byte order defaults to big within a word and word order to little across words.
"""

from __future__ import annotations

import json
import math
import os
import re
import struct
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ctui import Argument, CommandError, CommandResult, IntegerRanges, command
from tabulate import tabulate

from ctmodbus.formatting import timestamp

TABLES = ("coils", "discrete_inputs", "input_registers", "holding_registers")
CREATE_TABLES = {
    "coil": "coils",
    "discrete_input": "discrete_inputs",
    "input_register": "input_registers",
    "holding_register": "holding_registers",
}
REGISTER_TABLES = ("input_registers", "holding_registers")
WRITABLE_TABLES = ("coils", "holding_registers")
TYPE_FORMATS = {
    "uint8": (1, "B"),
    "int8": (1, "b"),
    "uint16": (2, "H"),
    "int16": (2, "h"),
    "uint32": (4, "I"),
    "int32": (4, "i"),
    "uint64": (8, "Q"),
    "int64": (8, "q"),
    "float32": (4, "f"),
    "float64": (8, "d"),
}
TYPES = ("bool", *TYPE_FORMATS)
NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\Z")
INTEGER_PATTERN = re.compile(
    r"(?P<sign>[+-]?)(?:(?P<prefix>0[bBoOdDxX])(?P<digits>[0-9A-Fa-f_]+)|"
    r"(?P<decimal>[0-9][0-9_]*))\Z"
)


@dataclass(frozen=True)
class Tag:
    """Immutable definition of one bit or a scalar occupying 1–4 registers.

    Construction alone does not validate; call validate() at input boundaries.
    table uses plural protocol identifiers even though tag create takes singular
    names. Addresses are zero-based; type derives width. No connection identity
    or current value is stored. Eight-bit types still occupy a complete register.
    """

    name: str
    table: str
    address: int
    type: str
    byte_order: str = "big"
    word_order: str = "little"

    @property
    def count(self):
        """Return the number of Modbus addresses occupied by the tag."""
        if self.type == "bool":
            return 1
        size, _ = TYPE_FORMATS[self.type]
        return 1 if size == 1 else size // 2

    @property
    def stop(self):
        """Return the exclusive end address."""
        return self.address + self.count

    def validate(self):
        """Return self when valid; raise CommandError for invalid definitions.

        Require NAME_PATTERN, supported table/type/order, and the entire derived
        span inside 0..65535. Bool uses bit tables; numeric types use register
        tables. Explicit order options on bool are rejected at command/import
        boundaries, not by this internal representation.
        """
        if not isinstance(self.name, str) or not NAME_PATTERN.fullmatch(self.name):
            raise CommandError(
                "Tag names must start with a letter or underscore and contain only "
                "letters, digits, underscores, dots, or hyphens"
            )
        if self.table not in TABLES:
            raise CommandError(f"Tag table must be one of: {', '.join(TABLES)}")
        if self.type not in TYPES:
            raise CommandError(f"Tag type must be one of: {', '.join(TYPES)}")
        if self.type == "bool" and self.table not in TABLES[:2]:
            raise CommandError("bool tags require coils or discrete_inputs")
        if self.type != "bool" and self.table not in REGISTER_TABLES:
            raise CommandError(
                "Numeric tags require input_registers or holding_registers"
            )
        if self.byte_order not in ("big", "little"):
            raise CommandError("byte-order must be big or little")
        if self.word_order not in ("big", "little"):
            raise CommandError("word-order must be big or little")
        if (
            type(self.address) is not int
            or not 0 <= self.address <= 65535
            or self.stop > 65536
        ):
            raise CommandError("Tag addresses must be between 0 and 65535")
        return self

    def as_dict(self):
        """Return a stable TOML-compatible representation."""
        values = {"table": self.table, "address": self.address, "type": self.type}
        if self.type != "bool":
            values.update(
                byte_order=self.byte_order,
                word_order=self.word_order,
            )
        return values


class TagStore:
    """Persist tags using the backend's currently open SQLite connection.

    No live values or transport identities are stored. Methods create the table
    lazily, and mutations commit then touch project metadata. The backend owns
    connection lifetime. Calls are not protected by a store lock; callers must
    coordinate transactions and project changes. Unexpected SQL errors propagate.
    """

    CREATE = """CREATE TABLE IF NOT EXISTS tags(
        name TEXT PRIMARY KEY, table_name TEXT NOT NULL, address INTEGER NOT NULL,
        type_name TEXT NOT NULL, byte_order TEXT NOT NULL, word_order TEXT NOT NULL)"""

    def __init__(self, backend):
        """Retain the project backend without opening or creating a database."""
        self.backend = backend

    async def ensure(self):
        """Create the table if absent and commit; return None.

        ctui migrations cover older projects, but new-project initialization
        does not execute those migrations, so reads also call this lazy hook.
        It commits the shared connection and must not interleave another writer.
        """
        await self.backend.connection.execute(self.CREATE)
        await self.backend.connection.commit()

    @staticmethod
    def _row(row):
        """Return a validated Tag from the six-column stored tuple."""
        return Tag(*row).validate()

    async def list(self):
        """Return all active-project tags ordered by name."""
        await self.ensure()
        cursor = await self.backend.connection.execute(
            "SELECT name, table_name, address, type_name, byte_order, word_order "
            "FROM tags ORDER BY name"
        )
        return [self._row(row) for row in await cursor.fetchall()]

    async def get(self, name):
        """Return the exact-name Tag; raise CommandError if absent or invalid."""
        await self.ensure()
        cursor = await self.backend.connection.execute(
            "SELECT name, table_name, address, type_name, byte_order, word_order "
            "FROM tags WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise CommandError(f"Unknown tag: {name!r}")
        return self._row(row)

    async def names(self):
        """Return a set of active-project names after validating stored definitions."""
        return {tag.name for tag in await self.list()}

    async def save(self, tag, *, replace=False):
        """Validate and commit tag; return None, replacing only if requested.

        Duplicate names become CommandError. Roll back SQL failures; other
        exceptions propagate. Metadata touch happens after the data commit.
        """
        tag.validate()
        await self.ensure()
        sql = (
            "INSERT OR REPLACE INTO tags VALUES (?, ?, ?, ?, ?, ?)"
            if replace
            else "INSERT INTO tags VALUES (?, ?, ?, ?, ?, ?)"
        )
        try:
            await self.backend.connection.execute(
                sql,
                (
                    tag.name,
                    tag.table,
                    tag.address,
                    tag.type,
                    tag.byte_order,
                    tag.word_order,
                ),
            )
            await self.backend.connection.commit()
        except Exception as error:
            await self.backend.connection.rollback()
            if "UNIQUE constraint failed" in str(error):
                raise CommandError(f"Tag {tag.name!r} already exists") from error
            raise
        await self.backend.touch()

    async def delete(self, name):
        """Delete NAME and return None; CommandError rejects absent/invalid tags."""
        await self.get(name)
        await self.backend.connection.execute(
            "DELETE FROM tags WHERE name = ?", (name,)
        )
        await self.backend.connection.commit()
        await self.backend.touch()

    async def rename(self, name, new_name):
        """Rename NAME and return None without changing its definition.

        Invalid/missing names and duplicate destinations raise CommandError;
        SQL failures roll back and propagate. Touch metadata after committing.
        """
        Tag(new_name, "coils", 0, "bool").validate()
        await self.get(name)
        try:
            await self.backend.connection.execute(
                "UPDATE tags SET name = ? WHERE name = ?", (new_name, name)
            )
            await self.backend.connection.commit()
        except Exception as error:
            await self.backend.connection.rollback()
            if "UNIQUE constraint failed" in str(error):
                raise CommandError(f"Tag {new_name!r} already exists") from error
            raise
        await self.backend.touch()

    async def clear(self):
        """Delete every tag in the active project."""
        await self.ensure()
        await self.backend.connection.execute("DELETE FROM tags")
        await self.backend.connection.commit()
        await self.backend.touch()

    async def import_all(self, tags, *, replace=False):
        """Commit prevalidated tags in one transaction and return None.

        Caller must validate every definition and settle replacement policy
        before calling. SQL errors roll back all rows and propagate. The later
        metadata touch is separate from the committed transaction. Cancellation
        is not caught by the ordinary-exception rollback handler.
        """
        await self.ensure()
        sql = (
            "INSERT OR REPLACE INTO tags VALUES (?, ?, ?, ?, ?, ?)"
            if replace
            else "INSERT INTO tags VALUES (?, ?, ?, ?, ?, ?)"
        )
        await self.backend.connection.execute("BEGIN")
        try:
            for tag in tags:
                await self.backend.connection.execute(
                    sql,
                    (
                        tag.name,
                        tag.table,
                        tag.address,
                        tag.type,
                        tag.byte_order,
                        tag.word_order,
                    ),
                )
            await self.backend.connection.commit()
        except Exception:
            await self.backend.connection.rollback()
            raise
        await self.backend.touch()


def _parse_integer(text):
    """Return a signed integer from decimal or 0b/0o/0d/0x text.

    Strip underscores from matched digits and accept an optional leading sign.
    Malformed text or digits invalid for the radix raise ValueError. Width and
    two's-complement interpretation are handled by callers.
    """
    match = INTEGER_PATTERN.fullmatch(text)
    if not match:
        raise ValueError("expected an integer or 0b/0o/0d/0x literal")
    digits = (match.group("digits") or match.group("decimal")).replace("_", "")
    prefix = (match.group("prefix") or "0d").lower()
    base = {"0b": 2, "0o": 8, "0d": 10, "0x": 16}[prefix]
    value = int(digits, base)
    return -value if match.group("sign") == "-" else value


def parse_tag_value(tag, text):
    """Return bool, int, or float parsed for an already validated tag.

    Bool accepts case-insensitive 0/1, false/true, off/on. Integer syntax follows
    _parse_integer; unsigned nondecimal literals fitting a signed tag's bit width
    use two's complement, while explicit signs and decimal stay numeric. Floats
    accept decimal/scientific text or integer literals converted numerically,
    never raw IEEE bits. Reject non-finite input with CommandError. Integer and
    float32 range validation is deferred to encode_tag_value.
    """
    if tag.type == "bool":
        values = {
            "0": False,
            "false": False,
            "off": False,
            "1": True,
            "true": True,
            "on": True,
        }
        try:
            return values[text.lower()]
        except KeyError as error:
            raise CommandError(
                "Boolean tag values must be 0/1, false/true, or off/on"
            ) from error
    try:
        if tag.type.startswith("float"):
            try:
                value = float(text.replace("_", ""))
            except ValueError:
                value = float(_parse_integer(text))
            if not math.isfinite(value):
                raise ValueError("non-finite values are not supported")
            return value
        value = _parse_integer(text)
        if tag.type.startswith("int"):
            match = INTEGER_PATTERN.fullmatch(text)
            prefix = (match.group("prefix") or "0d").lower()
            if not match.group("sign") and prefix != "0d":
                size, _ = TYPE_FORMATS[tag.type]
                bits = size * 8
                if 2 ** (bits - 1) <= value < 2**bits:
                    value -= 2**bits
        return value
    except (ValueError, OverflowError) as error:
        raise CommandError(f"Invalid {tag.type} value {text!r}: {error}") from error


def encode_tag_value(tag, value):
    """Return wire integers for a validated tag and parsed value.

    Bool returns one 0/1 value. Numeric values use struct widths and the tag's
    byte/word order; overflow becomes CommandError. Eight-bit values zero-pad
    the unused byte (including negative int8), deliberately avoiding a
    read-modify-write race. This function assumes parse_tag_value already
    rejected non-finite floats; it is not a general input-validation boundary.
    """
    if tag.type == "bool":
        return [int(value)]
    size, format_code = TYPE_FORMATS[tag.type]
    try:
        packed = struct.pack(">" + format_code, value)
    except (struct.error, OverflowError) as error:
        raise CommandError(f"Value is outside the range for {tag.type}") from error
    if size == 1:
        packed = b"\x00" + packed
    words = [packed[index : index + 2] for index in range(0, len(packed), 2)]
    if tag.word_order == "little":
        words.reverse()
    if tag.byte_order == "little":
        words = [word[::-1] for word in words]
    return [int.from_bytes(word, "big") for word in words]


def decode_tag_value(tag, values):
    """Return a Python scalar from exactly tag.count validated wire values.

    Reverse byte/word transforms and ignore the unused byte for 8-bit tags.
    Raw floating-point NaN/infinity can be decoded even though write input
    rejects them. Caller validates lengths and wire ranges; malformed direct
    calls may raise IndexError, OverflowError, or struct.error.
    """
    if tag.type == "bool":
        return bool(values[0])
    words = [int(value).to_bytes(2, "big") for value in values]
    if tag.byte_order == "little":
        words = [word[::-1] for word in words]
    if tag.word_order == "little":
        words.reverse()
    packed = b"".join(words)
    size, format_code = TYPE_FORMATS[tag.type]
    if size == 1:
        packed = packed[1:]
    return struct.unpack(">" + format_code, packed)[0]


def parse_tag_document(path):
    """Synchronously read PATH and return validated Tag objects in file order.

    Require ctmodbus-tags format/version 1 and a tags table; reject unknown
    per-tag fields and Boolean order options. Convert file, TOML, and definition
    failures to CommandError. No project mutations occur here. Whole files are
    read without a size limit; callers currently invoke this on the event loop.
    """
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CommandError(f"Cannot import tags: {error}") from error
    if document.get("format") != "ctmodbus-tags" or document.get("version") != 1:
        raise CommandError("Unsupported tag export format")
    definitions = document.get("tags")
    if not isinstance(definitions, dict):
        raise CommandError("Tag export must contain a tags table")
    tags = []
    for name, values in definitions.items():
        if not isinstance(values, dict):
            raise CommandError(f"Tag {name!r} must be a TOML table")
        unknown = set(values) - {
            "table",
            "address",
            "type",
            "byte_order",
            "word_order",
        }
        if unknown:
            raise CommandError(
                f"Tag {name!r} has unknown fields: {', '.join(sorted(unknown))}"
            )
        try:
            if values.get("type") == "bool" and (
                "byte_order" in values or "word_order" in values
            ):
                raise CommandError("Boolean tags do not accept byte or word order")
            tag = Tag(
                name=name,
                table=values["table"],
                address=values["address"],
                type=values["type"],
                byte_order=values.get("byte_order", "big"),
                word_order=values.get("word_order", "little"),
            ).validate()
        except (KeyError, TypeError, CommandError) as error:
            raise CommandError(f"Invalid tag {name!r}: {error}") from error
        tags.append(tag)
    return tags


def export_tag_document(tags):
    """Return versioned TOML text for validated tags in caller-supplied order.

    Quote names, include numeric order settings, and emit an empty tags table
    even with no definitions. Perform no file I/O or additional validation.
    """
    lines = ['format = "ctmodbus-tags"', "version = 1", "", "[tags]"]
    for tag in tags:
        lines.extend(("", f"[tags.{json.dumps(tag.name)}]"))
        for key, value in tag.as_dict().items():
            rendered = json.dumps(value) if isinstance(value, str) else str(value)
            lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"


async def complete_tags(context):
    """Complete tag names from the active project."""
    return sorted(await context.app.tags.names())


TAG_ORDER_ARGUMENTS = {
    "byte_order": Argument(flags=("--byte-order",)),
    "word_order": Argument(flags=("--word-order",)),
}


class TagCommandMixin:
    """Commands for typed tags using app-owned tags and protocol services.

    ctui signatures/decorators define command syntax. Read/write/create/rename/
    delete return append CommandResult; listing, inspection, and file commands
    return text. Expected input/protocol errors use CommandError. Store and
    unexpected file errors can propagate; no mixin-wide serialization is added.
    """

    @command(name="tag create", arguments=TAG_ORDER_ARGUMENTS)
    async def tag_create(
        self,
        name: str,
        table: Literal["coil", "discrete_input", "input_register", "holding_register"],
        address: int,
        type_name: Literal[
            "bool",
            "uint8",
            "int8",
            "uint16",
            "int16",
            "uint32",
            "int32",
            "uint64",
            "int64",
            "float32",
            "float64",
        ],
        byte_order: Literal["big", "little"] | None = None,
        word_order: Literal["little", "big"] | None = None,
    ):
        """Create NAME TABLE ADDRESS TYPE with optional byte/word order flags.

        Accept singular tables and derive width from type; normalize storage to
        plural tables. Defaults are big bytes/little words. Reject duplicate
        names and Boolean order flags with CommandError. Overlap is legal and
        produces a warning after save because alternate decodings are useful.
        """
        if type_name == "bool" and (byte_order is not None or word_order is not None):
            raise CommandError("Boolean tags do not accept byte or word order")
        stored_table = CREATE_TABLES[table]
        tag = Tag(
            name,
            stored_table,
            address,
            type_name,
            byte_order or "big",
            word_order or "little",
        ).validate()
        overlaps = [
            item.name
            for item in await self.tags.list()
            if item.table == tag.table
            and item.address < tag.stop
            and tag.address < item.stop
        ]
        await self.tags.save(tag)
        output = (
            f"Created tag {name!r}: {stored_table} "
            f"{address}-{tag.stop - 1} {type_name}"
        )
        if overlaps:
            output += "\nWarning: overlaps tags: " + ", ".join(overlaps)
        return CommandResult.append(output)

    @command(name="tag list")
    async def tag_list(self):
        """List tags in the active project."""
        tags = await self.tags.list()
        if not tags:
            return "No tags."
        return tabulate(
            [
                (
                    tag.name,
                    tag.table,
                    tag.address,
                    tag.count,
                    tag.type,
                    "-" if tag.type == "bool" else tag.byte_order,
                    "-" if tag.type == "bool" else tag.word_order,
                )
                for tag in tags
            ],
            headers=("Name", "Table", "Address", "Count", "Type", "Byte", "Word"),
        )

    @command(name="tag show", arguments={"name": Argument(completer=complete_tags)})
    async def tag_show(self, name: str):
        """Show one tag and its derived address range."""
        tag = await self.tags.get(name)
        values = tag.as_dict()
        values["range"] = f"{tag.address}-{tag.stop - 1}"
        return "\n".join(f"{key}: {value}" for key, value in values.items())

    @command(name="tag rename", arguments={"name": Argument(completer=complete_tags)})
    async def tag_rename(self, name: str, new_name: str):
        """Rename a tag in the active project."""
        await self.tags.rename(name, new_name)
        return CommandResult.append(f"Renamed tag {name!r} to {new_name!r}")

    @command(name="tag delete", arguments={"name": Argument(completer=complete_tags)})
    async def tag_delete(self, name: str):
        """Delete a tag from the active project."""
        await self.tags.delete(name)
        return CommandResult.append(f"Deleted tag {name!r}")

    @command(name="read tags", arguments={"names": Argument(completer=complete_tags)})
    async def read_tags(self, names: list[str] | None = None):
        """Read all tags, or comma-separated names in the requested order.

        Resolve every name before I/O; None selects name-sorted project tags.
        Empty selections and unknown names raise CommandError. Each tag gets a
        separate read reservation, preserving explicit order and duplicates;
        this is not a single snapshot. Return decoded and raw columns only after
        all reads succeed. Earlier tag rows are currently lost on later failure;
        read_values_data supplies only the failing tag's partial error output.
        """
        requested = names
        if requested is None:
            requested = [tag.name for tag in await self.tags.list()]
        if not requested:
            raise CommandError("No tags are defined in the active project")
        tags = [await self.tags.get(name) for name in requested]
        rows = []
        for tag in tags:
            addresses = str(tag.address)
            if tag.count > 1:
                addresses += f"-{tag.stop - 1}"
            result = await self.read_values_data(
                tag.table,
                IntegerRanges(addresses),
                min(tag.count, 2000 if tag.type == "bool" else 125),
            )
            raw = [value for _, value in result]
            rows.append(
                (
                    tag.name,
                    decode_tag_value(tag, raw),
                    tag.type,
                    ",".join(f"0x{int(value):04X}" for value in raw),
                )
            )
        return CommandResult.append(
            f"{timestamp()} Read tags\n"
            + tabulate(rows, headers=("Tag", "Value", "Type", "Raw"))
        )

    @command(name="write tag", arguments={"name": Argument(completer=complete_tags)})
    async def write_tag(self, name: str, value: str):
        """Execute ``write tag NAME VALUE`` through the validated write path.

        Use ``--`` before negative positional values. Reject read-only tables
        and bad encodings before I/O; return decoded input and raw acknowledged
        values. write_values owns serialization and uncertain-write errors.
        Acknowledgement does not establish independent device readback.
        """
        tag = await self.tags.get(name)
        if tag.table not in WRITABLE_TABLES:
            raise CommandError(f"{tag.table} tags are read-only")
        typed = parse_tag_value(tag, value)
        encoded = encode_tag_value(tag, typed)
        result = await self.write_values(tag.table, tag.address, encoded)
        return CommandResult.append(
            f"{timestamp()} Write tag acknowledged: {name} = {typed!r}\n"
            f"Raw: {', '.join(f'0x{item:04X}' for item in encoded)}\n"
            f"{result.output}"
        )

    @command(name="tag export")
    async def tag_export(self, path: Path):
        """Write name-sorted project tags to PATH and return destination text.

        Append .toml unless the existing suffix matches case-insensitively.
        Synchronously write PATH.tmp then os.replace the destination. The rename
        is atomic, but the fixed temporary name is not safe for concurrent
        exports to the same path. OSError becomes CommandError after cleanup.
        """
        if path.suffix.lower() != ".toml":
            path = path.with_name(path.name + ".toml")
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_text(
                export_tag_document(await self.tags.list()), encoding="utf-8"
            )
            os.replace(temporary, path)
        except OSError as error:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise CommandError(f"Cannot export tags: {error}") from error
        return f"Exported tags to {path}."

    @command(
        name="tag import",
        arguments={"replace": Argument(flags=("--replace",))},
    )
    async def tag_import(self, path: Path, replace: bool = False):
        """Validate PATH and merge tags, returning the imported count as text.

        Reject existing names unless replace=True. TUI confirmation is prepared
        separately by ModbusApp.prepare_tag_import; direct calls never prompt.
        The file is reread here. Ordinary SQL failures roll back imported rows;
        cancellation and project races are documented as open discrepancies.
        """
        tags = parse_tag_document(path)
        collisions = sorted({tag.name for tag in tags} & await self.tags.names())
        if collisions and not replace:
            raise CommandError(
                "Tags already exist: "
                + ", ".join(collisions)
                + ". Re-run with --replace to overwrite them."
            )
        await self.tags.import_all(tags, replace=replace)
        return f"Imported {len(tags)} tags."
