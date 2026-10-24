"""Versioned, project-persisted server definitions; no live sockets or values.

Tables have a fallback policy and nonoverlapping ranges. Named tag rules overlay
raw ranges and derive widths through the existing codecs. Validate everything
before changing project state. Files contain settings, never Python source.
"""

import copy
import json
import math
import os
import tempfile
import tomllib
from pathlib import Path

from ctui import CommandError

from ctmodbus.tags import TABLES, TAG_FIELDS, Tag, encode_tag_value

CONFIG_NAME = "ctmodbus-server"

IDENTITY = {
    "vendor": "ControlThings",
    "product": "ctmodbus simulator",
    "revision": "1.0",
}
MODES = {"static", "random", "sequence"}


def definition(full=True):
    """Return independent default or empty maps with no expanded addresses."""
    return {
        "format": "ctmodbus-server",
        "version": 1,
        "unit": 1,
        "identity": dict(IDENTITY),
        "tags": {},
        "hooks": {},
        "tables": {
            table: {
                "unmapped": "default" if full else "illegal",
                "default": False if table in TABLES[:2] else 0,
                "ranges": [],
            }
            for table in TABLES
        },
    }


def tag_from(name, item):
    """Return a validated codec definition from a server tag entry."""
    return Tag(
        name,
        item["table"],
        item["address"],
        item["type"],
        item.get("byte_order", "big"),
        item.get("word_order", "little"),
    ).validate()


def validate_value(value, table, tag=None):
    """Validate exact raw integers/bits or a finite typed scalar before serving."""
    if tag:
        if tag.type == "bool" and type(value) not in (bool, int):
            raise CommandError("Boolean values must be true/false or 0/1")
        if tag.type == "bool" and value not in (0, 1):
            raise CommandError("Boolean values must be true/false or 0/1")
        if tag.type.startswith(("int", "uint")) and type(value) is not int:
            raise CommandError("Integer tags require integer values")
        if tag.type.startswith("float") and (
            type(value) not in (int, float) or not math.isfinite(value)
        ):
            raise CommandError("Float tags require finite values")
        encode_tag_value(tag, value)
    elif type(value) not in (int, bool) or not 0 <= value <= (
        1 if table in TABLES[:2] else 65535
    ):
        raise CommandError(f"Invalid raw value for {table}: {value!r}")
    return value


def validate_rule(rule, table, tag=None):
    """Check one static/random/sequence rule and reject contradictory options."""
    mode = rule.get("mode", "static")
    allowed = {"start", "end", "mode"} | {
        "static": {"value"},
        "random": {"min", "max"},
        "sequence": {"values", "advance", "interval_seconds", "repeat"},
    }.get(mode, set())
    if mode not in MODES:
        raise CommandError(
            f"Unknown rule mode {mode!r}; use static, random, or sequence"
        )
    reject_unknown(rule, allowed, f"{table} {mode} rule")
    if mode == "static":
        validate_value(
            rule.get("value", False if table in TABLES[:2] else 0), table, tag
        )
    elif mode == "random":
        low, high = rule.get("min", 0), rule.get(
            "max", 1 if table in TABLES[:2] else 65535
        )
        validate_value(low, table, tag)
        validate_value(high, table, tag)
        if low > high:
            raise CommandError("Random minimum must not exceed maximum")
    else:
        values = rule.get("values")
        if not isinstance(values, list) or not values:
            raise CommandError("Sequences require a nonempty values list")
        for value in values:
            validate_value(value, table, tag)
        if (
            rule.get("advance", "read") not in ("read", "time")
            or type(rule.get("repeat", True)) is not bool
        ):
            raise CommandError("Invalid sequence advance/repeat")
        if rule.get("advance", "read") == "time":
            interval = rule.get("interval_seconds")
            if (
                type(interval) not in (int, float)
                or not math.isfinite(interval)
                or interval <= 0
            ):
                raise CommandError(
                    "Timed sequences require a positive interval_seconds"
                )
        elif "interval_seconds" in rule:
            raise CommandError("Read sequences do not accept interval_seconds")


def reject_unknown(mapping, allowed, location):
    """Report exact invalid keys and allowed replacements before normalization."""
    if not isinstance(mapping, dict):
        raise CommandError(f"{location} must be a TOML table")
    unknown = set(mapping) - set(allowed)
    if unknown:
        obsolete = ""
        if "tick_seconds" in unknown:
            obsolete = "; tick_seconds is obsolete: use tick_interval_seconds"
        raise CommandError(
            f"Unknown keys in {location}: {', '.join(sorted(unknown))}{obsolete}. "
            f"Allowed keys: {', '.join(sorted(allowed))}"
        )


def validate(config):  # pylint: disable=too-many-branches,too-many-statements
    """Require format/version markers; normalize validated sparse rules.

    Unknown or obsolete keys fail with their location and accepted keys. This
    applies equally to imported files and project-saved definitions; no legacy
    migration occurs. Validation never imports hooks or opens device I/O.
    """
    try:
        reject_unknown(
            config,
            {
                "format",
                "version",
                "unit",
                "identity",
                "tables",
                "tags",
                "hooks",
                "seed",
            },
            "server definition",
        )
        if config.get("format") != "ctmodbus-server":
            raise CommandError('Server definition requires format = "ctmodbus-server"')
        if type(config.get("version")) is not int or config["version"] != 1:
            raise CommandError("Server definition requires integer version = 1")
        if (
            type(config.get("unit", 1)) is not int
            or not 1 <= config.get("unit", 1) <= 247
        ):
            raise CommandError("Server unit ID must be an integer in 1–247")
        result = definition(False)
        result.update(copy.deepcopy(config))
        if "seed" in result and type(result["seed"]) is not int:
            raise CommandError("Random seed must be an integer")
        reject_unknown(result["identity"], IDENTITY, "identity")
        identity = {**IDENTITY, **result["identity"]}
        if set(identity) - set(IDENTITY) or any(
            not isinstance(v, str) or len(v.encode()) > 200 for v in identity.values()
        ):
            raise CommandError(
                "Identity requires vendor/product/revision strings "
                "up to 200 UTF-8 bytes"
            )
        result["identity"] = identity
        reject_unknown(result["tables"], TABLES, "tables")
        if not isinstance(result["tags"], dict):
            raise CommandError("tags must be a TOML table")
        for table, settings in result["tables"].items():
            reject_unknown(
                settings, {"unmapped", "default", "ranges"}, f"tables.{table}"
            )
        result["tables"] = {
            table: {
                "unmapped": "illegal",
                "default": False if table in TABLES[:2] else 0,
                "ranges": [],
                **result["tables"].get(table, {}),
            }
            for table in TABLES
        }
        for table, settings in result["tables"].items():
            if set(settings) - {"unmapped", "default", "ranges"} or settings[
                "unmapped"
            ] not in ("illegal", "default"):
                raise CommandError(f"Invalid settings for {table}")
            validate_value(settings["default"], table)
            if not isinstance(settings["ranges"], list):
                raise CommandError(f"tables.{table}.ranges must be an array of tables")
            spans = []
            for rule in settings["ranges"]:
                if not isinstance(rule, dict):
                    raise CommandError(f"tables.{table}.ranges entries must be tables")
                start, end = rule["start"], rule.get("end", rule["start"])
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 0 <= start <= end <= 65535
                ):
                    raise CommandError("Ranges must fit addresses 0–65535")
                if any(
                    start <= other_end and other_start <= end
                    for other_start, other_end in spans
                ):
                    raise CommandError(f"Overlapping ranges in {table}")
                spans.append((start, end))
                rule["end"] = end
                validate_rule(rule, table)
        spans = {table: [] for table in TABLES}
        for name, item in result["tags"].items():
            reject_unknown(
                item,
                TAG_FIELDS
                | {
                    "mode",
                    "value",
                    "min",
                    "max",
                    "values",
                    "advance",
                    "interval_seconds",
                    "repeat",
                },
                f"tags.{name}",
            )
            tag = tag_from(name, item)
            rule = {k: v for k, v in item.items() if k not in TAG_FIELDS}
            if any(
                tag.address < stop and start < tag.stop
                for start, stop in spans[tag.table]
            ):
                raise CommandError("Server behavior tags must not overlap")
            spans[tag.table].append((tag.address, tag.stop))
            validate_rule(rule, tag.table, tag)
        hooks = result["hooks"]
        reject_unknown(
            hooks,
            {"module", "on_read", "on_write", "on_tick", "tick_interval_seconds"},
            "hooks",
        )
        if "tick_interval_seconds" in hooks and "on_tick" not in hooks:
            raise CommandError("tick_interval_seconds requires on_tick")
        if any(
            not isinstance(v, str) or not v
            for k, v in hooks.items()
            if k != "tick_interval_seconds"
        ):
            raise CommandError("Hook paths and function names must be nonempty strings")
        if any(
            k in hooks for k in ("on_read", "on_write", "on_tick")
        ) and not hooks.get("module"):
            raise CommandError("Hooks require a Python module path")
        if "on_tick" in hooks:
            interval = hooks.get("tick_interval_seconds", 1)
            if (
                type(interval) not in (int, float)
                or not math.isfinite(interval)
                or interval <= 0
            ):
                raise CommandError("tick_interval_seconds must be positive and finite")
        return result
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise CommandError(f"Invalid server definition: {error}") from error


def load(path):
    """Read TOML once and resolve the companion hook path relative to its file."""
    path = path.expanduser().resolve()
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CommandError(f"Cannot import server configuration: {error}") from error
    config = validate(config)
    if config["hooks"].get("module"):
        config["hooks"]["module"] = str(
            (path.parent / config["hooks"]["module"]).resolve()
        )
    return config


def dumps(config):
    """Serialize normalized definitions deterministically without another dependency."""
    lines = []

    def scalar(value):
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, list):
            return "[" + ", ".join(scalar(v) for v in value) + "]"
        return str(value)

    def emit(mapping, prefix=()):
        for key, value in mapping.items():
            if not isinstance(value, dict) and not (
                isinstance(value, list) and value and isinstance(value[0], dict)
            ):
                lines.append(f"{json.dumps(key)} = {scalar(value)}")
        for key, value in mapping.items():
            name = ".".join(json.dumps(part) for part in (*prefix, key))
            if isinstance(value, dict):
                lines.extend(("", f"[{name}]"))
                emit(value, (*prefix, key))
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                for item in value:
                    lines.extend(("", f"[[{name}]]"))
                    emit(item, (*prefix, key))

    emit(validate(config))
    return "\n".join(lines) + "\n"


def export(config, path):
    """Atomically export a definition with hook paths relative to the destination."""
    path = path.expanduser().resolve()
    if not path.suffix:
        path = path.with_suffix(".toml")
    config = copy.deepcopy(config)
    if config["hooks"].get("module"):
        config["hooks"]["module"] = os.path.relpath(
            config["hooks"]["module"], path.parent
        )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(dumps(config))
        temporary.replace(path)
    except OSError as error:
        raise CommandError(f"Cannot export server data: {error}") from error
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return path
