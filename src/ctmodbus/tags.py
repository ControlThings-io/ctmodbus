"""Project-scoped typed Modbus tags and portable TOML files."""

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
    """A named typed view of one bit or one or more registers."""

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
        """Reject definitions that cannot be mapped to Modbus addresses."""
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
    """Persist tags in the active ctui project database."""

    CREATE = """CREATE TABLE IF NOT EXISTS tags(
        name TEXT PRIMARY KEY, table_name TEXT NOT NULL, address INTEGER NOT NULL,
        type_name TEXT NOT NULL, byte_order TEXT NOT NULL, word_order TEXT NOT NULL)"""

    def __init__(self, backend):
        self.backend = backend

    async def ensure(self):
        """Create the application table for new projects when first used."""
        await self.backend.connection.execute(self.CREATE)
        await self.backend.connection.commit()

    @staticmethod
    def _row(row):
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
        """Return one tag or raise a user-facing error."""
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
        """Return the active project's tag names."""
        return {tag.name for tag in await self.list()}

    async def save(self, tag, *, replace=False):
        """Persist one validated tag."""
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
        """Delete an existing tag."""
        await self.get(name)
        await self.backend.connection.execute(
            "DELETE FROM tags WHERE name = ?", (name,)
        )
        await self.backend.connection.commit()
        await self.backend.touch()

    async def rename(self, name, new_name):
        """Rename an existing tag without changing its definition."""
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
        """Import a validated collection in one transaction."""
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
    match = INTEGER_PATTERN.fullmatch(text)
    if not match:
        raise ValueError("expected an integer or 0b/0o/0d/0x literal")
    digits = (match.group("digits") or match.group("decimal")).replace("_", "")
    prefix = (match.group("prefix") or "0d").lower()
    base = {"0b": 2, "0o": 8, "0d": 10, "0x": 16}[prefix]
    value = int(digits, base)
    return -value if match.group("sign") == "-" else value


def parse_tag_value(tag, text):
    """Parse a natural typed value without depending on a raw byte syntax."""
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
    """Encode a typed value into unsigned 16-bit Modbus register values."""
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
    """Decode Modbus bits/registers according to a tag definition."""
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
    """Load and fully validate a versioned tag TOML document."""
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
    """Render deterministic TOML without adding another dependency."""
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
    """Commands for typed, project-scoped Modbus tags."""

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
        """Create a typed tag; its address count is derived from its type."""
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
        """Read all tags, or comma-separated names in the requested order."""
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
        """Parse and write a value according to a tag's declared type."""
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

    @command(name="export tags")
    async def export_tags(self, path: Path):
        """Export all active-project tags to versioned TOML."""
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
        name="import tags",
        arguments={"replace": Argument(flags=("--replace",))},
    )
    async def import_tags(self, path: Path, replace: bool = False):
        """Import a validated TOML tag set atomically."""
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
