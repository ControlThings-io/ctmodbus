"""Transient evidence views for client observations and downstream responses.

A write acknowledgement is not readback. Keep read and write evidence separately,
with UTC timestamps and request identities, so partial tag reads cannot become
fabricated complete typed values. No observations are persisted across sessions.
"""

from tabulate import tabulate

from ctmodbus.formatting import timestamp
from ctmodbus.tags import decode_tag_value

READ_TABLES = {
    "read_coils": "coils",
    "read_discrete_inputs": "discrete_inputs",
    "read_holding_registers": "holding_registers",
    "read_input_registers": "input_registers",
}
WRITE_TABLES = {
    "write_coil": "coils",
    "write_coils": "coils",
    "write_register": "holding_registers",
    "write_registers": "holding_registers",
}


class DataState:
    """Track last successful reads and attempted writes per raw table/address."""

    def __init__(self, label="No session"):
        self.label = label
        self.rows = {}
        self.serial = 0
        self.identity = {}
        self.identity_at = ""

    def read(self, table, address, values):
        """Record a complete validated response as one coherent observation."""
        self.serial += 1
        when = timestamp()
        for offset, value in enumerate(values):
            self.rows.setdefault((table, address + offset), {}).update(
                read=int(value), read_at=when, request=self.serial
            )

    def write(self, table, address, values, outcome):
        """Record attempted/acknowledged/uncertain writes without inventing reads."""
        self.serial += 1
        when = timestamp()
        for offset, value in enumerate(values):
            self.rows.setdefault((table, address + offset), {}).update(
                write_request=self.serial,
                write=int(value),
                write_at=when,
                outcome=outcome,
            )

    def identification(self, information):
        """Keep the last observed identification objects, including continued pages."""
        self.identity.update(
            {int(key): repr(value) for key, value in information.items()}
        )
        self.identity_at = timestamp()

    def record(self, direction, item):
        """Consume existing decoded operation records for the client-only view."""
        operation = item.get("operation")
        if direction == "received" and operation == "read_device_information":
            self.identification(item.get("information", {}))
        if direction == "received" and operation in READ_TABLES and "values" in item:
            self.read(READ_TABLES[operation], item["address"], item["values"])
        if operation in WRITE_TABLES and "values" in item:
            outcome = (
                "acknowledged; no readback"
                if item.get("acknowledged")
                else (
                    ("uncertain" if item.get("sent", True) else "not sent")
                    if direction == "error"
                    else "attempted"
                )
            )
            self.write(
                WRITE_TABLES[operation], item["address"], item["values"], outcome
            )

    def show(self, tags):
        """Render tags, partial accesses, raw evidence, and explicit unknown values."""
        lines = [
            self.label,
            "Values are last observations, not a live device snapshot.",
        ]
        if self.identity:
            lines.append(
                f"Device identification observed at {self.identity_at}: {self.identity}"
            )
        tag_rows = []
        for tag in tags:
            items = [
                self.rows.get((tag.table, address), {})
                for address in range(tag.address, tag.stop)
            ]
            complete = (
                all("read" in item for item in items)
                and len({item.get("request") for item in items}) == 1
            )
            value = "unknown" if not any(items) else "partial / separate reads"
            if complete:
                try:
                    value = repr(
                        decode_tag_value(tag, [item["read"] for item in items])
                    )
                except (ValueError, OverflowError):
                    value = "undecodable"
            tag_rows.append(
                (tag.name, tag.table, f"{tag.address}-{tag.stop - 1}", value)
            )
        if tag_rows:
            lines.append(
                tabulate(tag_rows, headers=("Tag", "Table", "Address", "Read value"))
            )
        raw = [
            (
                table,
                address,
                item.get("read", "unknown"),
                item.get("read_at", "—"),
                item.get("write", "—"),
                item.get("outcome", "—"),
                item.get("write_at", "—"),
                (
                    ("matches" if item["read"] == item["write"] else "differs")
                    if "write" in item
                    and "read" in item
                    and item.get("request", 0) > item.get("write_request", 0)
                    else "not read back"
                ),
            )
            for (table, address), item in sorted(self.rows.items())
        ]
        lines.append(
            tabulate(
                raw,
                headers=(
                    "Table",
                    "Address",
                    "Last read",
                    "Read UTC",
                    "Last write",
                    "Write outcome",
                    "Write UTC",
                    "Readback",
                ),
            )
            if raw
            else "No observed addresses."
        )
        return "\n".join(lines)
