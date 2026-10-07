"""Fixed-cadence, application-owned polling with serialized read evidence.

Polls snapshot targets and the connection generation. Busy ticks are discarded,
never queued; one cycle reserves the connection across its ordered columns.
Runtime state is not persisted. Background output uses the shared ctui layout.
"""

import asyncio
import math
from dataclasses import dataclass

from ctui import (
    Argument,
    CommandError,
    CommandResult,
    IntegerRanges,
    IntegerSpan,
    command,
)

from ctmodbus.operations import READ_LIMITS, read_chunks
from ctmodbus.tags import Tag, complete_tags, decode_tag_value

LIMIT_ARGUMENTS = {
    name: Argument(flags=(f"--{name}",)) for name in ("interval", "count", "duration")
}
TABLE_ARGUMENTS = {
    name: Argument(flags=(f"--{name.replace('_', '-')}",)) for name in READ_LIMITS
}


@dataclass(frozen=True)
class PollColumn:
    """Immutable display column with validated chunks and an optional tag codec."""

    label: str
    table: str
    chunks: tuple[IntegerSpan, ...]
    tag: Tag | None = None


class PollTable:
    """Format append-only rows with stable widths and a header on expansion.

    Reserve integer type bounds, float precision, full raw sequences, and ERR.
    Numeric tags/counters align right; booleans/raw sequences align left.
    Floats use 9 significant digits for float32 and 17 for float64, retaining
    round-trip precision with compact scientific notation when appropriate.
    Unlimited counters start at six characters; bounded counters use at least
    three. Overflow widens future rows and repeats the header without rewriting
    previously appended output. Labels and values supplied here are safe ASCII.
    """

    def __init__(self, columns: tuple[PollColumn, ...], count: int | None):
        """Calculate initial widths from the target plan and optional cycle limit."""
        self.labels = ["#", *(column.label for column in columns)]
        self.right = [
            True,
            *(
                column.tag is not None and column.tag.type != "bool"
                for column in columns
            ),
        ]
        self.widths = [max(3, len(str(count))) if count is not None else 6]
        for column in columns:
            if column.tag is None:
                size = sum(chunk.count for chunk in column.chunks)
                width = (
                    size
                    if column.table in ("coils", "discrete_inputs")
                    else size * 5 - 1
                )
            elif column.tag.type == "bool":
                width = 5
            elif column.tag.type.startswith("float"):
                width = 17 if column.tag.type == "float32" else 25
            else:
                signed = column.tag.type.startswith("int")
                bits = int(column.tag.type.removeprefix("uint").removeprefix("int"))
                width = max(
                    len(str(-(1 << (bits - 1)))) if signed else 0,
                    len(str((1 << (bits - int(signed))) - 1)),
                )
            self.widths.append(max(3, len(column.label), width))

    def format(self, cells: list[str]) -> str:
        """Return one padded line with a separator between every pair of columns."""
        return " | ".join(
            value.rjust(width) if right else value.ljust(width)
            for value, width, right in zip(cells, self.widths, self.right)
        ).rstrip()

    def header(self) -> str:
        """Return the current padded header, headed by #."""
        return self.format(self.labels)

    def row(self, number: int, values: list[str]) -> list[str]:
        """Return a row, preceded by a new header if any cell requires expansion."""
        cells = [str(number), *values]
        widths = [max(width, len(value)) for width, value in zip(self.widths, cells)]
        changed = widths != self.widths
        self.widths = widths
        return ([self.header()] if changed else []) + [self.format(cells)]

    @staticmethod
    def tag_value(tag: Tag, value: bool | int | float) -> str:
        """Render a decoded scalar compactly without changing recorded raw evidence."""
        if tag.type.startswith("float"):
            text = format(value, ".9g" if tag.type == "float32" else ".17g")
            if math.isfinite(value) and "." not in text and "e" not in text:
                text += ".0"
            return text
        return repr(value)


class Poll:  # pylint: disable=protected-access
    """Own a timer and at most one cycle; stop gracefully or abort during shutdown.

    Deadlines use loop.time(), beginning immediately. Count limits started
    cycles; duration bounds cycle starts, allowing an active cycle to finish.
    Errors stay local to columns while the transport remains usable. Status is
    retained after completion. All requests use existing validated read helpers.
    """

    def __init__(self, app):
        """Initialize idle runtime state without creating tasks or device I/O."""
        self.app = app
        self.task = None
        self.cycle = None
        self.stop_event = asyncio.Event()
        self.columns = ()
        self.table = PollTable((), None)
        self.interval = 1.0
        self.count = self.duration = None
        self.started = self.completed = self.skipped = self.failed_columns = 0
        self.last_duration = 0.0
        self.reason = "No poll started"
        self.generation = None

    @property
    def active(self):
        """Whether the timer or its final draining cycle is still running."""
        return self.task is not None and not self.task.done()

    def append(self, text):
        """Append one safe line/header to TUI/WUI output or the CLI stream."""
        stream = self.app._poll_stdout
        if stream is not None:
            print(text, file=stream, flush=True)
            return
        layout = getattr(self.app, "layout", None)
        current = layout.output_field.text if layout else self.app.output_text
        output = f"{current.rstrip()}\n{text}" if current else text
        self.app.output_text = output
        if layout:
            layout.set_output(output)
        runtime = getattr(self.app, "app", None)
        if runtime:
            runtime.invalidate()

    async def start(self, columns, interval, count, duration):
        """Validate limits/session; reject replacement and empty targets.

        CLI callers wait for completion and stream rows; TUI/WUI return at once.
        No await occurs between validation and task ownership assignment.
        """
        if self.active:
            raise CommandError("A poll is already running; use poll stop first")
        if not columns:
            raise CommandError("Provide polling targets; no tags or tables selected")
        for name, value in (("interval", interval), ("duration", duration)):
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(value) or value <= 0
            ):
                raise CommandError(f"{name} must be finite and greater than zero")
        if count is not None and (type(count) is not int or count < 1):
            raise CommandError("count must be a positive integer")
        if not self.app.connection.connected:
            raise CommandError("No connected session; connect first")
        self.columns = tuple(columns)
        self.table = PollTable(self.columns, count)
        self.interval, self.count, self.duration = interval, count, duration
        self.generation = self.app.connection.generation
        self.started = self.completed = self.skipped = self.failed_columns = 0
        self.last_duration = 0.0
        self.reason = "Running"
        self.stop_event = asyncio.Event()
        self.task = asyncio.create_task(self.run(), name="modbus-poll")
        if self.app._poll_stdout is not None:
            await self.task
        return CommandResult.success()

    async def run(self):  # pylint: disable=too-many-branches,too-many-statements
        """Schedule fixed deadlines, skip busy/late ticks, and drain the last cycle."""
        loop = asyncio.get_running_loop()
        origin = loop.time()
        tick = 0
        self.append(self.table.header())
        try:
            while not self.stop_event.is_set():
                if self.count is not None and self.started >= self.count:
                    self.reason = "Count limit reached"
                    break
                now = loop.time()
                deadline = origin + tick * self.interval
                if self.duration is not None and deadline >= origin + self.duration:
                    self.reason = "Duration limit reached"
                    break
                delay = max(0, deadline - now)
                try:
                    await asyncio.wait_for(self.stop_event.wait(), delay)
                    break
                except TimeoutError:
                    pass
                if self.stop_event.is_set():
                    break
                now = loop.time()
                # Event-loop delays discard obsolete deadlines without catch-up.
                overdue = max(0, int((now - deadline) / self.interval))
                self.skipped += overdue
                tick += overdue
                if self.duration is not None and now >= origin + self.duration:
                    self.reason = "Duration limit reached"
                    break
                connection = self.app.connection
                if connection.generation != self.generation or not connection.connected:
                    self.reason = "Connection lost or replaced"
                    break
                if (
                    self.cycle is not None and not self.cycle.done()
                ) or connection.lock.locked():
                    self.skipped += 1
                else:
                    if self.cycle is not None:
                        await self.cycle
                    self.started += 1
                    self.cycle = asyncio.create_task(self.read_cycle(self.started))
                    # Let the cycle acquire or decline the reservation before
                    # evaluating a count limit. No device response is awaited.
                    await asyncio.sleep(0)
                tick += 1
            if self.cycle is not None:
                await self.cycle
        except asyncio.CancelledError:
            self.reason = "Cancelled; connection closed"
            if self.cycle is not None and not self.cycle.done():
                self.cycle.cancel()
                await asyncio.gather(self.cycle, return_exceptions=True)
            raise
        except Exception as error:  # pylint: disable=broad-exception-caught
            self.reason = f"Poll failed: {error}"
        finally:
            if self.cycle is not None and not self.cycle.done():
                self.cycle.cancel()
                await asyncio.gather(self.cycle, return_exceptions=True)
            self.append(f"Poll stopped: {self.reason}")

    async def read_cycle(  # pylint: disable=too-many-branches,too-many-statements
        self, number
    ):
        """Append one ordered row, retaining confirmed raw prefixes on column errors."""
        # A manual operation may acquire the lock between timer and task turns.
        # Decline that tick rather than enqueue behind it.
        if self.app.connection.lock.locked():
            self.started -= 1
            self.skipped += 1
            return
        started = asyncio.get_running_loop().time()
        values = []
        try:
            async with self.app.connection.operation() as (client, settings):
                if self.app.connection.generation != self.generation:
                    raise CommandError("Polling session replaced")
                for column in self.columns:
                    raw = []
                    rendered = "ERR"
                    failed = False
                    if not self.app.connection.connected:
                        failed = True
                    else:
                        try:
                            for chunk in column.chunks:
                                pairs = await self.app.read_reserved_chunks(
                                    column.table, [chunk], client, settings
                                )
                                raw.extend(value for _, value in pairs)
                            if column.tag:
                                try:
                                    rendered = self.table.tag_value(
                                        column.tag, decode_tag_value(column.tag, raw)
                                    )
                                except CommandError as error:
                                    await self.app.record_operation(
                                        "error",
                                        {
                                            "operation": "poll_decode",
                                            "tag": column.tag.name,
                                            "error": str(error),
                                            "cycle": number,
                                        },
                                    )
                                    raise
                        except CommandError:
                            failed = True
                    if column.tag:
                        value = "ERR" if failed else rendered
                    else:
                        value = (
                            "".join(str(int(item)) for item in raw)
                            if column.table in ("coils", "discrete_inputs")
                            else " ".join(f"{int(item):04X}" for item in raw)
                        )
                        if failed:
                            value = (value + " ERR").strip()
                    values.append(value)
                    self.failed_columns += int(failed)
                if not self.app.connection.connected:
                    self.reason = "Connection lost"
                    self.stop_event.set()
        except (CommandError, asyncio.CancelledError) as error:
            missing = len(self.columns) - len(values)
            values.extend(["ERR"] * missing)
            self.failed_columns += missing
            self.reason = "Connection lost or cancelled"
            self.stop_event.set()
            if isinstance(error, asyncio.CancelledError):
                self.app.connection.abort()
        finally:
            self.last_duration = asyncio.get_running_loop().time() - started
            self.completed += 1
            for line in self.table.row(number, values):
                self.append(line)
            warnings = self.app._record_warnings.pop(asyncio.current_task(), [])
            if warnings:
                self.append("Recording warning: " + "; ".join(dict.fromkeys(warnings)))

    async def stop(self, *, abort=False):
        """Stop future ticks; optionally cancel active I/O for connection shutdown."""
        if not self.active:
            return
        self.reason = "Stopped by user"
        self.stop_event.set()
        if abort:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        else:
            await self.task


class PollCommandMixin:
    """Typed polling commands shared by terminal, browser, and CLI dispatch."""

    @command(
        name="poll tags",
        arguments={
            **LIMIT_ARGUMENTS,
            "names": Argument(
                help="Comma-separated tag names; omit to poll all",
                completer=complete_tags,
            ),
        },
    )
    async def poll_tags(
        self,
        names: list[str] | None = None,
        interval: float = 1,
        count: int | None = None,
        duration: float | None = None,
    ):
        """Poll selected decoded tags in input order; default to all in name order."""
        tags = (
            [await self.tags.get(name) for name in names]
            if names is not None
            else await self.tags.list()
        )
        columns = [
            PollColumn(tag.name, tag.table, (IntegerSpan(tag.address, tag.count),), tag)
            for tag in tags
        ]
        return await self.poller.start(columns, interval, count, duration)

    @command(name="poll raw", arguments={**LIMIT_ARGUMENTS, **TABLE_ARGUMENTS})
    async def poll_raw(
        self,
        coils: IntegerRanges | None = None,
        discrete_inputs: IntegerRanges | None = None,
        input_registers: IntegerRanges | None = None,
        holding_registers: IntegerRanges | None = None,
        interval: float = 1,
        count: int | None = None,
        duration: float | None = None,
    ):
        """Poll each inclusive raw range as a column, respecting table-option order.

        Validate the complete plan before starting; preserve overlaps/repetitions.
        Direct Python callers use signature table order. Bit/register requests
        split at their protocol limits and retain completed chunks on failure.
        """
        tables = {
            "coils": coils,
            "discrete_inputs": discrete_inputs,
            "input_registers": input_registers,
            "holding_registers": holding_registers,
        }
        order = self._poll_orders.get(asyncio.current_task(), list(tables))
        columns = []
        for table in order:
            addresses = tables[table]
            if addresses is None:
                continue
            limit = READ_LIMITS[table]
            list(read_chunks(addresses, limit, limit))
            for span in addresses:
                chunks = tuple(read_chunks(IntegerRanges([span]), limit, limit))
                columns.append(PollColumn(f"{table}:{span}", table, chunks))
        return await self.poller.start(columns, interval, count, duration)

    @command(name="poll status")
    def poll_status(self):
        """Show retained limits, targets, counts, errors, and last cycle duration."""
        poll = self.poller
        return CommandResult.append(
            f"{'Running' if poll.active else 'Stopped'}: {poll.reason}\n"
            f"interval={poll.interval:g}s, count={poll.count}, "
            f"duration={poll.duration}\n"
            f"started={poll.started}, completed={poll.completed}, "
            f"skipped={poll.skipped}, "
            f"failed_columns={poll.failed_columns}, "
            f"last_duration={poll.last_duration:.3f}s\n"
            + "Targets: "
            + ", ".join(column.label for column in poll.columns)
        )

    @command(name="poll stop")
    async def poll_stop(self):
        """Stop scheduling, drain the current cycle, and retain the connection."""
        await self.poller.stop()
        return CommandResult.append("Polling is stopped.")
