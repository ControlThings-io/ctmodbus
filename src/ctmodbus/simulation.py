"""Sparse local emulation with transactional hooks and coherent typed responses.

Raw ranges provide values; named tags overlay them. Dynamic rules sample once
per request, including partial tag accesses. A local request uses a transaction
copy: failures leave values, sequence positions and RNG state unchanged.
"""

import asyncio
import importlib.util
import inspect
import random
import time
from pathlib import Path

from ctui import CommandError

from ctmodbus.server_config import tag_from, validate, validate_value
from ctmodbus.tags import decode_tag_value, encode_tag_value


class HookDevice:
    """Hook API over the pending local transaction; set never invokes hooks."""

    def __init__(self, simulator):
        self.simulator = simulator

    def get(self, name):
        """Decode a tag from the current request snapshot, sampling it once."""
        tag = self.simulator.tags.get(name)
        if tag is None:
            raise CommandError(f"Unknown server tag: {name}")
        return decode_tag_value(tag, self.simulator.tag_values(name))

    def set(self, name, value):
        """Set a complete typed tag in pending state, bypassing on_write."""
        tag = self.simulator.tags.get(name)
        if tag is None:
            raise CommandError(f"Unknown server tag: {name}")
        validate_value(value, tag.table, tag)
        values = encode_tag_value(tag, value)
        for offset, raw in enumerate(values):
            self.simulator.values[tag.table, tag.address + offset] = raw
        self.simulator.sampled[name] = values


class Simulator:
    """Own sparse runtime values, RNG and sequence indexes for one server run."""

    def __init__(self, config, hooks=None, clock=time.monotonic):
        self.config = validate(config)
        self.tags = {
            name: tag_from(name, item) for name, item in config["tags"].items()
        }
        self.hooks = hooks or {}
        self.clock = clock
        self.started = clock()
        self.values = {}
        self.indexes = {}
        self.sampled = {}
        self.rng = random.Random(config.get("seed"))
        self.lock = asyncio.Lock()
        self.sample_time = self.started
        self.advance_reads = False

    @staticmethod
    def load_hooks(config):
        """Load trusted companion code; validate named callables without invoking
        hooks.
        """
        hooks = config["hooks"]
        if not hooks.get("module"):
            return {}
        path = Path(hooks["module"])
        try:
            spec = importlib.util.spec_from_file_location("ctmodbus_device_hook", path)
            if spec is None or spec.loader is None:
                raise ValueError("Cannot load Python module")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = {}
            for name in ("on_read", "on_write", "on_tick"):
                if name in hooks:
                    function = getattr(module, hooks[name])
                    if not callable(function):
                        raise ValueError(f"{hooks[name]} is not callable")
                    result[name] = function
            return result
        except Exception as error:
            raise CommandError(f"Cannot load server hooks: {error}") from error

    def rule_value(self, key, rule, table, tag=None):
        """Generate one bounded scalar; read sequences advance on transaction commit."""
        mode = rule.get("mode", "static")
        if mode == "static":
            return rule.get(
                "value", False if table in ("coils", "discrete_inputs") else 0
            )
        if mode == "random":
            low, high = rule.get("min", 0), rule.get(
                "max", 1 if table in ("coils", "discrete_inputs") else 65535
            )
            return (
                self.rng.uniform(low, high)
                if tag and tag.type.startswith("float")
                else self.rng.randint(int(low), int(high))
            )
        values = rule["values"]
        if rule.get("advance", "read") == "time":
            index = int((self.sample_time - self.started) / rule["interval_seconds"])
        else:
            index = self.indexes.get(key, 0)
            if self.advance_reads:
                self.indexes[key] = index + 1
        return values[
            (
                index % len(values)
                if rule.get("repeat", True)
                else min(index, len(values) - 1)
            )
        ]

    def tag_values(self, name):
        """Return one generated typed value per request; static tags honor writes."""
        if name in self.sampled:
            return self.sampled[name]
        tag, rule = self.tags[name], self.config["tags"][name]
        values = encode_tag_value(
            tag, self.rule_value(("tag", name), rule, tag.table, tag)
        )
        if rule.get("mode", "static") == "static":
            values = [
                self.values.get((tag.table, tag.address + offset), value)
                for offset, value in enumerate(values)
            ]
        self.sampled[name] = values
        return values

    def available(self, table, address):
        """Check address availability without allocating its default value."""
        settings = self.config["tables"][table]
        return (
            settings["unmapped"] == "default"
            or any(
                rule["start"] <= address <= rule["end"] for rule in settings["ranges"]
            )
            or any(
                tag.table == table and tag.address <= address < tag.stop
                for tag in self.tags.values()
            )
        )

    def read(self, table, address, count):
        """Produce sparse raw values, with full-width tag samples for partial reads."""
        result = []
        for current in range(address, address + count):
            name = next(
                (
                    name
                    for name, tag in self.tags.items()
                    if tag.table == table and tag.address <= current < tag.stop
                ),
                None,
            )
            if name:
                result.append(self.tag_values(name)[current - self.tags[name].address])
                continue
            settings = self.config["tables"][table]
            rule = next(
                (
                    rule
                    for rule in settings["ranges"]
                    if rule["start"] <= current <= rule["end"]
                ),
                None,
            )
            if rule:
                key = (table, current)
                value = self.rule_value(key, rule, table)
                if rule.get("mode", "static") == "static":
                    value = self.values.get(key, value)
            else:
                value = self.values.get((table, current), settings["default"])
            result.append(int(value))
        return result

    async def hook(self, name, *args):
        """Invoke optional synchronous/async trusted code against pending state."""
        if name in self.hooks:
            async with asyncio.timeout(3):
                result = self.hooks[name](HookDevice(self), *args)
                if inspect.isawaitable(result):
                    await result

    async def transaction(self, callback, advance_reads=False):
        """Serialize local operations and roll back all pending hook/rule changes."""
        async with self.lock:
            before = (dict(self.values), dict(self.indexes), self.rng.getstate())
            self.sampled = {}
            self.sample_time = self.clock()
            self.advance_reads = advance_reads
            try:
                return await callback()
            except BaseException:
                self.values, self.indexes = before[:2]
                self.rng.setstate(before[2])
                raise
            finally:
                self.sampled = {}

    async def access(self, table, address, count, values=None):
        """Apply one request; validate its entire range before hooks or mutations."""
        if not all(
            self.available(table, current)
            for current in range(address, address + count)
        ):
            raise CommandError("Illegal data address")

        async def execute():
            names = [
                name
                for name, tag in self.tags.items()
                if tag.table == table
                and tag.address < address + count
                and address < tag.stop
            ]
            if values is None:
                await self.hook("on_read", tuple(names))
                return self.read(table, address, count)
            for offset, value in enumerate(values):
                self.values[table, address + offset] = int(value)
            for name in names:
                tag = self.tags[name]
                if address <= tag.address and tag.stop <= address + count:
                    raw = values[tag.address - address : tag.stop - address]
                    self.sampled[name] = list(raw)
                    await self.hook("on_write", name, decode_tag_value(tag, raw))
            return list(values)

        return await self.transaction(execute, advance_reads=values is None)

    async def tick(self, elapsed):
        """Apply one periodic hook atomically; caller records errors and keeps
        running.
        """

        async def execute():
            await self.hook("on_tick", elapsed)

        await self.transaction(execute)
