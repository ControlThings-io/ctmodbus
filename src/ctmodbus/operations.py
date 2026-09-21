"""Typed Modbus commands, validation, and response handling."""

import asyncio

from ctui import (
    Argument,
    CommandError,
    CommandResult,
    IntegerRanges,
    IntegerSpan,
    command,
)

from ctmodbus.formatting import format_identification, format_values, timestamp

READ_LIMITS = {
    "coils": 2000,
    "discrete_inputs": 2000,
    "input_registers": 125,
    "holding_registers": 125,
}
READ_ARGUMENTS = {"max_count": Argument(flags=("--max-count",))}


def read_chunks(addresses, max_count, limit):
    """Validate the entire request before yielding exclusive-endpoint spans."""
    if not 1 <= max_count <= limit:
        raise CommandError(f"max-count must be between 1 and {limit}")
    if any(span.stop > 65536 for span in addresses):
        raise CommandError("Addresses must be between 0 and 65535")
    if addresses.count > 65536:
        raise CommandError(
            "A read may contain at most 65536 addresses, including repeats"
        )
    for span in addresses:
        for start in range(span.start, span.stop, max_count):
            yield IntegerSpan(start, min(max_count, span.stop - start))


def validate_write(kind, address, values):
    """Reject invalid writes before issuing any protocol request."""
    limit = 1968 if kind == "coils" else 123
    maximum = 1 if kind == "coils" else 65535
    if not values or len(values) > limit:
        raise CommandError(f"Provide between 1 and {limit} values")
    if not 0 <= address <= 65535 or address + len(values) > 65536:
        raise CommandError("Write addresses must be between 0 and 65535")
    if any(type(value) is not int or not 0 <= value <= maximum for value in values):
        raise CommandError(f"{kind} values must be integers between 0 and {maximum}")


class ModbusCommandMixin:
    """Commands mixed into ModbusApp; connection and services belong to the app."""

    async def record_operation(self, direction, decoded):
        """Overridden by the application to persist decoded protocol records."""

    async def read_values_data(self, kind, addresses, max_count):
        """Read ordered chunks and return address/value pairs."""
        chunks = list(read_chunks(addresses, max_count, READ_LIMITS[kind]))
        results = []
        try:
            async with self.connection.operation() as (client, settings):
                for index, span in enumerate(chunks):
                    request = {
                        "operation": f"read_{kind}",
                        "address": span.start,
                        "count": span.count,
                        "unit": settings.unit,
                    }
                    await self.record_operation("sent", request)
                    response = await self.connection.request(
                        getattr(client, f"read_{kind}"),
                        address=span.start,
                        count=span.count,
                    )
                    expected_function = {
                        "coils": 1,
                        "discrete_inputs": 2,
                        "holding_registers": 3,
                        "input_registers": 4,
                    }[kind]
                    if getattr(response, "function_code", None) != expected_function:
                        raise CommandError("Read response has incorrect function")
                    attr = (
                        "bits" if kind in ("coils", "discrete_inputs") else "registers"
                    )
                    values = getattr(response, attr, None)
                    if (
                        values is None
                        or len(values) < span.count
                        or (attr == "registers" and len(values) != span.count)
                    ):
                        raise CommandError(
                            f"Invalid {kind} response length at address {span.start}"
                        )
                    values = values[
                        : span.count
                    ]  # Coil responses are padded to a byte.
                    if any(
                        not isinstance(value, (int, bool))
                        or not 0 <= value <= (1 if attr == "bits" else 65535)
                        for value in values
                    ):
                        raise CommandError(f"Invalid {kind} response values")
                    results.extend(zip(range(span.start, span.stop), values))
                    await self.record_operation(
                        "received", {**request, "values": list(values)}
                    )
                    await self.events.emit(
                        "modbus_progress", completed=index + 1, total=len(chunks)
                    )
        except asyncio.CancelledError as error:
            self.connection.abort()
            await self.record_operation(
                "error",
                {
                    "operation": f"read_{kind}",
                    "error": "cancelled",
                    "completed_addresses": len(results),
                },
            )
            raise CommandError(
                self.partial_read(kind, results, "Read cancelled; connection closed")
            ) from error
        except CommandError as error:
            await self.record_operation(
                "error",
                {
                    "operation": f"read_{kind}",
                    "error": str(error),
                    "completed_addresses": len(results),
                },
            )
            raise CommandError(self.partial_read(kind, results, str(error))) from error
        finally:
            await self.events.emit("modbus_progress", completed=0, total=0)
        return results

    async def read_values(self, kind, addresses, max_count):
        """Read ordered chunks and format the completed values."""
        results = await self.read_values_data(kind, addresses, max_count)
        return CommandResult.append(
            f"{timestamp()} Read {kind}\n{format_values(kind, results)}"
        )

    @staticmethod
    def partial_read(kind, results, message):
        """Include completed addresses in a failed read's error output."""
        if results:
            return (
                f"{message}\nPartial read: {len(results)} addresses completed\n"
                f"{format_values(kind, results)}"
            )
        return message

    @command(name="read coils", arguments=READ_ARGUMENTS)
    async def read_coils(self, addresses: IntegerRanges, max_count: int = 2000):
        """Read coils from inclusive comma-separated addresses/ranges."""
        return await self.read_values("coils", addresses, max_count)

    @command(name="read discrete_inputs", arguments=READ_ARGUMENTS)
    async def read_discrete_inputs(
        self, addresses: IntegerRanges, max_count: int = 2000
    ):
        """Read discrete inputs from inclusive addresses/ranges."""
        return await self.read_values("discrete_inputs", addresses, max_count)

    @command(name="read input_registers", arguments=READ_ARGUMENTS)
    async def read_input_registers(
        self, addresses: IntegerRanges, max_count: int = 125
    ):
        """Read input registers from inclusive addresses/ranges."""
        return await self.read_values("input_registers", addresses, max_count)

    @command(name="read holding_registers", arguments=READ_ARGUMENTS)
    async def read_holding_registers(
        self, addresses: IntegerRanges, max_count: int = 125
    ):
        """Read holding registers from inclusive addresses/ranges."""
        return await self.read_values("holding_registers", addresses, max_count)

    @command(name="read id")
    async def read_id(self):
        """Read basic device identification, including continued responses."""
        information, seen, object_id = {}, set(), 0
        try:
            async with self.connection.operation() as (client, settings):
                while True:
                    if object_id in seen or not 0 <= object_id <= 255:
                        raise CommandError("Invalid device identification continuation")
                    seen.add(object_id)
                    request = {
                        "operation": "read_device_information",
                        "object_id": object_id,
                        "unit": settings.unit,
                    }
                    await self.record_operation("sent", request)
                    response = await self.connection.request(
                        client.read_device_information, read_code=1, object_id=object_id
                    )
                    page = getattr(response, "information", None)
                    if not isinstance(page, dict) or not page:
                        raise CommandError("Device returned no identification objects")
                    if any(
                        type(key) is not int
                        or not 0 <= key <= 255
                        or not isinstance(value, (bytes, str))
                        for key, value in page.items()
                    ):
                        raise CommandError("Invalid device identification objects")
                    information.update(page)
                    await self.record_operation(
                        "received",
                        {
                            **request,
                            "information": {
                                str(key): repr(value) for key, value in page.items()
                            },
                        },
                    )
                    if not getattr(response, "more_follows", False):
                        break
                    object_id = response.next_object_id
        except asyncio.CancelledError as error:
            self.connection.abort()
            await self.record_operation(
                "error", {"operation": "read_device_information", "error": "cancelled"}
            )
            raise CommandError(
                "Identification read cancelled; connection closed"
            ) from error
        except CommandError as error:
            await self.record_operation(
                "error", {"operation": "read_device_information", "error": str(error)}
            )
            raise
        return CommandResult.append(
            f"{timestamp()} Device identification\n{format_identification(information)}"
        )

    async def write_values(self, kind, address, values):
        """Issue one write and verify the returned function, address and values."""
        validate_write(kind, address, values)
        multiple = len(values) > 1
        suffix = "coils" if kind == "coils" else "registers"
        method_name = f"write_{suffix if multiple else suffix[:-1]}"
        request = {"operation": method_name, "address": address, "values": values}
        sent = False
        try:
            async with self.connection.operation() as (client, settings):
                request["unit"] = settings.unit
                await self.record_operation("sent", request)
                wire_values = (
                    [bool(value) for value in values] if kind == "coils" else values
                )
                args = (
                    {"values": wire_values} if multiple else {"value": wire_values[0]}
                )
                sent = True
                response = await self.connection.request(
                    getattr(client, method_name), address=address, **args
                )
                expected_function = (
                    (15 if multiple else 5)
                    if kind == "coils"
                    else (16 if multiple else 6)
                )
                if (
                    getattr(response, "function_code", None) != expected_function
                    or getattr(response, "address", None) != address
                ):
                    raise CommandError(
                        "Write acknowledgement has incorrect function or address"
                    )
                if multiple:
                    if getattr(response, "count", None) != len(values):
                        raise CommandError("Write acknowledgement has incorrect count")
                else:
                    echoed = getattr(
                        response, "bits" if kind == "coils" else "registers", None
                    )
                    if echoed != wire_values:
                        raise CommandError("Write acknowledgement has incorrect value")
                await self.record_operation(
                    "received", {**request, "acknowledged": True}
                )
        except asyncio.CancelledError as error:
            self.connection.abort()
            message = "Write cancelled; connection closed. " + (
                "The device may have applied the write; outcome unknown."
                if sent
                else "No write was sent."
            )
            await self.record_operation("error", {**request, "error": message})
            raise CommandError(message) from error
        except CommandError as error:
            message = str(error) + ("; write outcome unconfirmed" if sent else "")
            await self.record_operation("error", {**request, "error": message})
            raise CommandError(message) from error
        return CommandResult.append(
            f"{timestamp()} Write acknowledged: {kind}\n"
            f"{format_values(kind, list(enumerate(values, address)))}"
        )

    @command(name="write coils")
    async def write_coils(self, address: int, values: list[int]):
        """Write one or more coils as comma-separated 0/1 values."""
        return await self.write_values("coils", address, values)

    @command(name="write holding_registers")
    async def write_holding_registers(self, address: int, values: list[int]):
        """Write one or more registers as comma-separated integers."""
        return await self.write_values("holding_registers", address, values)
