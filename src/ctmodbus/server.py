"""Owned async listeners and interchangeable emulator/proxy request routing.

PyModbus owns decoding/framing. Our request handler captures each decoded PDU
and downstream transaction before awaiting, avoiding mutable last-PDU state.
Only the existing read/write/identification feature set is implemented; other
functions return Illegal Function. No MITM rules are implemented here.
"""

import asyncio
import copy
import ssl
import struct

from ctui import CommandError
from pymodbus import FramerType
from pymodbus.constants import ExcCodes
from pymodbus.exceptions import ModbusException, ModbusIOException
from pymodbus.pdu import ExceptionResponse
from pymodbus.pdu.bit_message import (
    ReadCoilsRequest,
    ReadCoilsResponse,
    ReadDiscreteInputsRequest,
    ReadDiscreteInputsResponse,
    WriteMultipleCoilsRequest,
    WriteMultipleCoilsResponse,
    WriteSingleCoilRequest,
    WriteSingleCoilResponse,
)
from pymodbus.pdu.mei_message import ReadDeviceInformationResponse
from pymodbus.pdu.register_message import (
    ReadHoldingRegistersRequest,
    ReadHoldingRegistersResponse,
    ReadInputRegistersRequest,
    ReadInputRegistersResponse,
    WriteMultipleRegistersResponse,
    WriteSingleRegisterResponse,
)
from pymodbus.server import (
    ModbusSerialServer,
    ModbusTcpServer,
    ModbusTlsServer,
    ModbusUdpServer,
)
from pymodbus.server.requesthandler import ServerRequestHandler
from pymodbus.simulator import DataType, SimData, SimDevice
from pymodbus.transaction import TransactionManager

from ctmodbus.data_state import DataState
from ctmodbus.formatting import timestamp
from ctmodbus.server_config import validate
from ctmodbus.simulation import Simulator
from ctmodbus.tags import decode_tag_value

TABLES = {
    1: "coils",
    2: "discrete_inputs",
    3: "holding_registers",
    4: "input_registers",
    5: "coils",
    6: "holding_registers",
    15: "coils",
    16: "holding_registers",
}
RESPONSES = {
    1: ReadCoilsResponse,
    2: ReadDiscreteInputsResponse,
    3: ReadHoldingRegistersResponse,
    4: ReadInputRegistersResponse,
    5: WriteSingleCoilResponse,
    6: WriteSingleRegisterResponse,
    15: WriteMultipleCoilsResponse,
    16: WriteMultipleRegistersResponse,
}
LIMITS = {1: 2000, 2: 2000, 3: 125, 4: 125, 5: 1, 6: 1, 15: 1968, 16: 123}


class CountValidation:  # pylint: disable=too-few-public-methods
    """Delay count checks until routing so invalid wire requests receive exception
    03.
    """

    def verifyCount(self, max_count, count=-1):  # pylint: disable=invalid-name
        """Decode first; Server.route applies function-specific limits."""


class CoilRequest(WriteSingleCoilRequest):
    """Retain the original coil word to reject nonstandard Boolean encodings."""

    raw_coil = 0

    def decode(self, data):
        """Decode the PDU and retain its unnormalized Boolean word."""
        super().decode(data)
        self.raw_coil = struct.unpack(">HH", data[:4])[1]


REQUEST_CLASSES = [
    type(f"CountChecked{cls.__name__}", (CountValidation, cls), {})
    for cls in (
        ReadCoilsRequest,
        ReadDiscreteInputsRequest,
        ReadHoldingRegistersRequest,
        ReadInputRegistersRequest,
        WriteMultipleCoilsRequest,
    )
] + [CoilRequest]


class OwnedHandler(ServerRequestHandler):
    """Capture transaction state and track tasks for bounded shutdown."""

    def callback_data(self, data, addr=None):
        """Decode and capture every complete PDU, including pipelined TCP requests."""
        total = 0
        while total < len(data):
            try:
                used = TransactionManager.callback_data(self, data[total:], addr)
            except ModbusIOException as error:
                owner = self.server.owner
                owner.request_counter += 1
                owner.log_line(
                    "SERVER",
                    owner.request_counter,
                    f"peer={addr!r} unit={error.dev_id} "
                    f"function=0x{error.fcode or 0:02X} ERROR {error}",
                )
                self.server_send(
                    ExceptionResponse(
                        error.fcode or 0,
                        ExcCodes.ILLEGAL_FUNCTION,
                        device_id=error.dev_id,
                        transaction=error.transaction_id,
                    ),
                    addr,
                )
                return len(data)
            if not used:
                break
            total += used
            if self.last_pdu:
                self.handle_later()
        return total

    def handle_later(self):
        request, address = self.last_pdu, self.last_addr
        self.last_pdu = None
        if request is not None:
            task = asyncio.create_task(self.dispatch_request(request, address))
            self.server.owner.tasks.add(task)
            task.add_done_callback(self.server.owner.tasks.discard)

    async def dispatch_request(self, request, address):
        """Return a response through the original framing and transaction ID."""
        request_id = "?"
        try:
            peer = address or (
                self.transport.get_extra_info("peername") if self.transport else None
            )
            request_id = self.server.owner.begin_request(request, peer)
            if (
                self.server.owner.serial_device
                and request.dev_id != self.server.owner.config["unit"]
            ):
                return
            response = await self.server.owner.handle(request, request_id=request_id)
            response.transaction_id = request.transaction_id
            response.dev_id = request.dev_id
            self.server_send(response, address)
        except asyncio.CancelledError:
            pass
        except Exception as error:  # pylint: disable=broad-exception-caught
            self.server.owner.last_error = str(error)
            self.server.owner.log_line("SERVER", request_id, f"ERROR {error}")
            self.server_send(
                ExceptionResponse(
                    request.function_code,
                    ExcCodes.DEVICE_FAILURE,
                    device_id=request.dev_id,
                    transaction=request.transaction_id,
                ),
                address,
            )


class OwnedListener:  # pylint: disable=too-few-public-methods
    """Mixin coupling PyModbus listeners to application-owned request tasks."""

    trace_packet = None
    trace_pdu = None
    trace_connect = None
    owner = None

    def callback_new_connection(self):
        """Construct a handler that captures requests before awaiting."""
        return OwnedHandler(self, self.trace_packet, self.trace_pdu, self.trace_connect)


class TcpListener(OwnedListener, ModbusTcpServer):
    """Owned Modbus TCP listener."""


class UdpListener(OwnedListener, ModbusUdpServer):
    """Owned Modbus UDP listener."""


class TlsListener(OwnedListener, ModbusTlsServer):
    """Owned native Modbus TLS listener."""


class SerialListener(OwnedListener, ModbusSerialServer):
    """Owned RTU/ASCII serial listener."""


def server_tls(cert_file, key_file, ca_file):
    """Load server identity off the event loop; optionally require client
    certificates.
    """
    if not cert_file or not key_file:
        raise CommandError("serve tls requires --cert-file and --key-file")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file, password="")
    if ca_file:
        context.load_verify_locations(cafile=ca_file)
        context.verify_mode = ssl.CERT_REQUIRED
    return context


class Server:
    """One independent listener, sparse simulator, proxy mode and evidence view."""

    def __init__(self, app):
        self.app = app
        self.listener = None
        self.simulator = None
        self.config = None
        self.proxy = False
        self.tasks = set()
        self.tick_task = None
        self.stop_event = asyncio.Event()
        self.last_error = ""
        self.session = None
        self.state = DataState("No server session")
        self.label = "Stopped"
        self.endpoint = None
        self.request_lock = asyncio.Lock()
        self.lifecycle = asyncio.Lock()
        self.serial_device = None
        self.stopping = False
        self.request_logging = True
        self.proxy_logging = True
        self.request_counter = 0

    async def record(self, direction, item):
        """Record server exchanges without turning storage errors into protocol
        errors.
        """
        if self.session is not None:
            try:
                await self.app.records.append(
                    session=self.session,
                    protocol="modbus-server",
                    direction=direction,
                    decoded=item,
                )
            except Exception as error:  # pylint: disable=broad-exception-caught
                self.last_error = f"Recording warning: {error}"

    async def start(
        self, config, settings, cert_file=None, key_file=None, ca_file=None, quiet=False
    ):
        """Bind one listener; failure closes candidates and leaves the server
        stopped.
        """
        async with self.lifecycle:
            if self.listener is not None:
                raise CommandError("Server already running; use serve stop first")
            config = validate(config)
            if settings.transport in ("rtu", "ascii") and self.app.connection.settings:
                connected = self.app.connection.settings
                if (
                    connected.transport in ("rtu", "ascii")
                    and connected.target == settings.target
                ):
                    raise CommandError(
                        "Client and server cannot share the same serial port"
                    )
            hooks = await asyncio.to_thread(Simulator.load_hooks, config)
            # A dummy register supplies the decoder context, not the address map.
            context = SimDevice(
                id=config["unit"],
                simdata=[SimData(0, values=0, datatype=DataType.REGISTERS)],
            )
            options = {"ignore_missing_devices": False, "custom_pdu": REQUEST_CLASSES}
            if settings.transport in ("tcp", "udp", "tls"):
                cls = {"tcp": TcpListener, "udp": UdpListener, "tls": TlsListener}[
                    settings.transport
                ]
                options["address"] = (settings.target, settings.port)
                if settings.transport == "tls":
                    options["sslctx"] = await asyncio.to_thread(
                        server_tls, cert_file, key_file, ca_file
                    )
            else:
                cls = SerialListener
                options.update(
                    port=settings.target,
                    framer=(
                        FramerType.RTU
                        if settings.transport == "rtu"
                        else FramerType.ASCII
                    ),
                    baudrate=settings.baudrate,
                    bytesize=settings.bytesize,
                    parity=settings.parity,
                    stopbits=settings.stopbits,
                    reconnect_delay=0,
                )
            listener = cls(context, **options)
            listener.owner = self
            try:
                self.simulator = Simulator(config, hooks)
                self.config = config
                self.stop_event = asyncio.Event()
                self.proxy = False
                self.request_logging = not quiet
                self.proxy_logging = True
                self.last_error = ""
                self.state = DataState(f"Downstream {settings.label}")
                self.session = await self.app.records.start_session(
                    "modbus-server", metadata=settings.as_dict()
                )
                self.serial_device = (
                    settings.target if settings.transport in ("rtu", "ascii") else None
                )
                self.listener = listener
                await listener.serve_forever(background=True)
                port = settings.port
                if settings.transport in ("tcp", "tls"):
                    port = listener.transport.sockets[0].getsockname()[1]
                elif settings.transport == "udp":
                    port = listener.transport.get_extra_info("sockname")[1]
                self.label = f"{settings.transport.upper()} {settings.target}" + (
                    f":{port}" if settings.transport in ("tcp", "udp", "tls") else ""
                )
                self.endpoint = (
                    (settings.target, port)
                    if settings.transport in ("tcp", "udp", "tls")
                    else None
                )
                if "on_tick" in hooks:
                    self.tick_task = asyncio.create_task(self.ticks())
            except BaseException:
                await listener.shutdown()
                self.listener = None
                await self.finish_session()
                raise

    async def finish_session(self):
        """End durable server records in their original project."""
        session, self.session = self.session, None
        if session is not None:
            await self.app.records.end_session(session)

    async def stop(self):
        """Stop accepting requests, cancel/drain work, and close serial/network
        resources.
        """
        async with self.lifecycle:
            self.stopping = True
            try:
                listener, self.listener = self.listener, None
                if listener is not None:
                    await listener.shutdown()
                pending = self.tasks - {asyncio.current_task()}
                if self.tick_task:
                    pending.add(self.tick_task)
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True), 5
                    )
                self.tick_task = None
                self.proxy = False
                self.stop_event.set()
                await self.finish_session()
                self.label = "Stopped"

            finally:
                self.stopping = False

    async def ticks(self):
        """Periodic local-only hooks; failures are reported and pending changes
        rolled back.
        """
        previous = self.simulator.clock()
        while True:
            await asyncio.sleep(self.config["hooks"].get("tick_seconds", 1))
            now = self.simulator.clock()
            elapsed, previous = now - previous, now
            if self.proxy:
                continue
            try:
                async with self.request_lock:
                    await self.simulator.tick(elapsed)
            except Exception as error:  # pylint: disable=broad-exception-caught
                self.last_error = f"on_tick failed: {error}"
                self.log_line("SERVER", "-", f"ERROR {self.last_error}")
                await self.record(
                    "error", {"operation": "on_tick", "error": str(error)}
                )

    async def before_forward(self, request):
        """Future MITM request seam; currently identity, with no rule loading."""
        return request

    async def after_response(self, response):
        """Future MITM response seam; currently identity, with no rule loading."""
        return response

    @staticmethod
    def values(request):
        """Return payload values for supported write requests, trimming bit padding."""
        if request.function_code in (5, 15):
            return list(
                request.bits[: 1 if request.function_code == 5 else request.count]
            )
        return list(request.registers)

    def log_line(self, source, request_id, text):
        """Append a UTC line with escaped controls; errors bypass quiet settings."""
        safe = "".join(
            char if char.isprintable() else ascii(char)[1:-1] for char in str(text)
        )
        self.app.append_output(f"{timestamp()} {source:<6} #{request_id} {safe}")

    def request_summary(self, request):
        """Describe functions with at most 16 write values; records retain full data."""
        code = request.function_code
        if code not in TABLES:
            return "read id" if code == 43 else f"function=0x{code:02X}"
        count = request.count if code in (1, 2, 3, 4, 15, 16) else 1
        address = request.address
        end = address + count - 1
        selection = str(address) if count == 1 else f"{address}-{end}"
        summary = f"{'read' if code < 5 else 'write'} {TABLES[code]} {selection}"
        if code >= 5:
            values = self.values(request)
            preview = values[:16]
            text = (
                "".join(str(int(value)) for value in preview)
                if code in (5, 15)
                else " ".join(f"{int(value):04X}" for value in preview)
            )
            summary += f" values={text}"
            if len(values) > len(preview):
                summary += f" (+{len(values) - len(preview)} omitted)"
        return summary

    def begin_request(self, request, peer=None):
        """Assign a monotonic app-local ID and log arrival before serialization."""
        self.request_counter += 1
        request_id = self.request_counter
        if self.request_logging:
            self.log_line(
                "SERVER",
                request_id,
                f"peer={peer!r} unit={request.dev_id} {self.request_summary(request)}",
            )
        return request_id

    async def handle(self, request, *, request_id=None):
        """Log arrival, capture mode, serialize exchanges, and display failures."""
        proxy = self.proxy
        if request_id is None:
            request_id = self.begin_request(request)
        async with self.request_lock:
            response = await self.route(request, proxy, request_id)
        if response.isError():
            uncertain = (
                proxy
                and request.function_code in (5, 6, 15, 16)
                and response.exception_code == 11
            )
            self.log_line(
                "SERVER",
                request_id,
                f"ERROR exception={response.exception_code}"
                + ("; write outcome unconfirmed" if uncertain else ""),
            )
        return response

    async def route(self, request, proxy, request_id=None):
        # pylint: disable=too-many-return-statements,too-many-branches
        """Route a captured request using its mode, preserving valid-address
        semantics.
        """
        code = request.function_code
        if request.dev_id != self.config["unit"]:
            return ExceptionResponse(code, ExcCodes.GATEWAY_NO_RESPONSE)
        if code not in TABLES and code != 43:
            return ExceptionResponse(code, ExcCodes.ILLEGAL_FUNCTION)
        if code in TABLES:
            count = request.count if code in (1, 2, 3, 4, 15, 16) else 1
            if not 1 <= count <= LIMITS[code]:
                return ExceptionResponse(code, ExcCodes.ILLEGAL_VALUE)
            if not 0 <= request.address or request.address + count > 65536:
                return ExceptionResponse(code, ExcCodes.ILLEGAL_ADDRESS)
            if code == 5 and getattr(request, "raw_coil", 0) not in (0, 0xFF00):
                return ExceptionResponse(code, ExcCodes.ILLEGAL_VALUE)
            if code in (15, 16):
                expected = (count + 7) // 8 if code == 15 else count * 2
                actual = getattr(
                    request,
                    "data_byte_count" if code == 15 else "_payload_byte_count",
                    expected,
                )
                if request.byte_count != expected or actual != expected:
                    return ExceptionResponse(code, ExcCodes.ILLEGAL_VALUE)
        else:
            count = 0
        await self.record(
            "received",
            {
                "function": code,
                "request_id": request_id,
                "values": self.values(request) if code in (5, 6, 15, 16) else None,
                "unit": request.dev_id,
                "address": request.address,
                "count": count,
                "mode": "proxy" if proxy else "local",
            },
        )
        response = (
            await self.forward(request, request_id)
            if proxy
            else await self.local(request, count)
        )
        if code == 43 and not response.isError():
            self.state.identification(response.information)
        if code in TABLES:
            table = TABLES[code]
            if code < 5 and not response.isError():
                values = response.bits[:count] if code < 3 else response.registers
                self.state.read(table, request.address, values)
            elif code >= 5:
                self.state.write(
                    table,
                    request.address,
                    self.values(request),
                    (
                        "acknowledged; no readback"
                        if not response.isError()
                        else (
                            "possibly uncertain"
                            if proxy and response.exception_code == 11
                            else "rejected"
                        )
                    ),
                )
        await self.record(
            "sent",
            {
                "function": response.function_code,
                "request_id": request_id,
                "exception": response.exception_code,
                "registers": response.registers,
                "bits": response.bits,
                "tags": self.describe_tags(request, count, response),
            },
        )
        return response

    def describe_tags(self, request, count, response):
        """Label complete and partial accesses without inventing complete values."""
        table = TABLES.get(request.function_code)

        result = []
        for tag in self.simulator.tags.values():
            if tag.table != table or not (
                tag.address < request.address + count and request.address < tag.stop
            ):
                continue
            partial = not (
                request.address <= tag.address and tag.stop <= request.address + count
            )
            item = {"tag": tag.name, "partial": partial}
            if not partial and not response.isError():
                data = (
                    (
                        response.bits[:count]
                        if request.function_code < 3
                        else response.registers
                    )
                    if request.function_code < 5
                    else self.values(request)
                )
                raw = data[tag.address - request.address : tag.stop - request.address]
                item["value"] = repr(decode_tag_value(tag, raw))
                item["evidence"] = (
                    "read"
                    if request.function_code < 5
                    else "write acknowledgement, no readback"
                )
            result.append(item)
        return result

    async def local(self, request, count):  # pylint: disable=too-many-return-statements
        """Return local protocol responses; hook failures become Device Failure."""
        code = request.function_code
        if code == 43:
            if request.read_code not in (1, 2, 3, 4):
                return ExceptionResponse(code, ExcCodes.ILLEGAL_VALUE)
            identity = self.config["identity"]
            objects = {
                0: identity["vendor"].encode(),
                1: identity["product"].encode(),
                2: identity["revision"].encode(),
            }
            objects = {
                key: value
                for key, value in objects.items()
                if key == request.object_id
                or (request.read_code != 4 and key >= request.object_id)
            }
            if not objects:
                return ExceptionResponse(code, ExcCodes.ILLEGAL_ADDRESS)
            return ReadDeviceInformationResponse(
                read_code=request.read_code, information=objects
            )
        table = TABLES[code]
        if not all(
            self.simulator.available(table, address)
            for address in range(request.address, request.address + count)
        ):
            return ExceptionResponse(code, ExcCodes.ILLEGAL_ADDRESS)
        values = None if code < 5 else self.values(request)
        if values is not None and len(values) != count:
            return ExceptionResponse(code, ExcCodes.ILLEGAL_VALUE)
        try:
            result = await self.simulator.access(table, request.address, count, values)
        except Exception as error:  # pylint: disable=broad-exception-caught
            self.last_error = f"Local hook failed: {error}"
            await self.record("error", {"operation": "hook", "error": str(error)})
            return ExceptionResponse(code, ExcCodes.DEVICE_FAILURE)
        options = {"address": request.address, "count": count}
        if code in (1, 2, 5):
            options["bits"] = [bool(value) for value in result]
        elif code in (3, 4, 6):
            options["registers"] = result
        return RESPONSES[code](**options)

    @staticmethod
    def validate_acknowledgement(code, request, response, values):
        """Reject mismatched write echoes/counts before returning success."""
        if response.address != request.address:
            raise CommandError("Invalid upstream acknowledgement address")
        if code in (15, 16) and response.count != len(values):
            raise CommandError("Invalid upstream acknowledgement count")
        if code == 5 and response.bits != values:
            raise CommandError("Invalid upstream coil acknowledgement")
        if code == 6 and response.registers != values:
            raise CommandError("Invalid upstream register acknowledgement")

    async def forward(
        self, request, request_id=None
    ):  # pylint: disable=too-many-branches,too-many-statements
        """Forward decoded PDUs under the client lock with zero retries and
        faithful exceptions.
        """
        code = request.function_code
        sent = False
        try:
            async with self.app.connection.operation() as (client, settings):
                upstream = await self.before_forward(copy.deepcopy(request))
                upstream.dev_id = settings.unit
                if self.proxy_logging:
                    endpoint = settings.label.rsplit(" unit ", 1)[0]
                    self.log_line(
                        "PROXY",
                        request_id,
                        f"upstream={endpoint} unit={upstream.dev_id} "
                        f"{self.request_summary(upstream)}",
                    )
                values = self.values(upstream) if code in (5, 6, 15, 16) else None
                if values is not None:
                    self.app.client_state.write(
                        TABLES[code], upstream.address, values, "attempted"
                    )
                retries = client.ctx.retries
                client.ctx.retries = 0
                try:
                    sent = True
                    async with asyncio.timeout(settings.timeout + 1):
                        response = await client.execute(False, upstream)
                finally:
                    client.ctx.retries = retries
                if response is None or response.function_code not in (
                    code,
                    code | 0x80,
                ):
                    raise CommandError("Invalid upstream response function")
                if not response.isError() and code in (1, 2, 3, 4):
                    data = (
                        response.bits[: request.count]
                        if code < 3
                        else response.registers
                    )
                    if len(data) != request.count or any(
                        not isinstance(v, (int, bool))
                        or not 0 <= v <= (1 if code < 3 else 65535)
                        for v in data
                    ):
                        raise CommandError("Invalid upstream read response")
                    self.app.client_state.read(TABLES[code], upstream.address, data)
                if code == 43 and not response.isError():
                    self.app.client_state.identification(response.information)
                if values is not None:
                    if not response.isError():
                        self.validate_acknowledgement(code, upstream, response, values)
                    self.app.client_state.write(
                        TABLES[code],
                        upstream.address,
                        values,
                        (
                            "rejected"
                            if response.isError()
                            else "acknowledged; no readback"
                        ),
                    )
                response = await self.after_response(copy.deepcopy(response))
                if response.isError():
                    self.log_line(
                        "PROXY",
                        request_id,
                        f"ERROR upstream exception={response.exception_code}",
                    )
                return response
        except asyncio.CancelledError:
            self.log_line(
                "PROXY",
                request_id,
                "ERROR forwarding cancelled"
                + (
                    "; write outcome unconfirmed"
                    if sent and code in (5, 6, 15, 16)
                    else ""
                ),
            )
            if sent:
                self.app.connection.abort()
            if code in (5, 6, 15, 16):
                self.app.client_state.write(
                    TABLES[code],
                    request.address,
                    self.values(request),
                    "uncertain" if sent else "not sent",
                )
            if self.listener is not None and not self.stopping:
                return ExceptionResponse(code, ExcCodes.GATEWAY_NO_RESPONSE)
            raise
        except (CommandError, OSError, ModbusException, TimeoutError) as error:
            self.last_error = f"Proxy failed: {error}"
            uncertain = sent and code in (5, 6, 15, 16)
            self.log_line(
                "PROXY",
                request_id,
                f"ERROR {error}" + ("; write outcome unconfirmed" if uncertain else ""),
            )
            if code in (5, 6, 15, 16):
                self.app.client_state.write(
                    TABLES[code],
                    request.address,
                    self.values(request),
                    "uncertain" if sent else "not sent",
                )
            await self.record(
                "error",
                {
                    "operation": "proxy",
                    "error": str(error),
                    "write_uncertain": sent and code in (5, 6, 15, 16),
                },
            )
            return ExceptionResponse(code, ExcCodes.GATEWAY_NO_RESPONSE)
