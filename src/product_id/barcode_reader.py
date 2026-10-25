#Reads scanner
from __future__ import annotations
import logging
import time
from threading import Event
from typing import Callable, Protocol
LOG = logging.getLogger(__name__)

class ScannerError(RuntimeError):
    pass

class ScanCancelled(ScannerError):
    pass

class SerialTransport(Protocol):

    def read(self, size: int=1) -> bytes:
        ...

    def write(self, data: bytes) -> int:
        ...

    def flush(self) -> None:
        ...

    def reset_input_buffer(self) -> None:
        ...

    def close(self) -> None:
        ...

def build_config_command(pid: int, fid: int, value: bytes) -> bytes:
    width = fid >> 6
    if width < 3 and len(value) != width:
        raise ValueError(f'FID 0x{fid:02X} requires {width} parameter byte(s).')
    if len(value) > 65535:
        raise ValueError('Configuration value is too long.')
    length = len(value).to_bytes(2, 'big') if width == 3 else b''
    return bytes([0x21, pid, fid]) + length + value
#Configuration settings for now
GROCERY_PROFILE = (
    ('trigger mode', 0x61, 0x41, b'\x00'),
    ('plain output / no data packing', 0x51, 0x43, b'\x00'),
    ('empty barcode prefix', 0x51, 0xC1, b''),
    ('CR/LF barcode suffix', 0x51, 0xC2, b'\r\n'),
    ('suffix enabled', 0x51, 0x4C, b'\x01'),
    ('UPC-A enabled', 0x24, 0x41, b'\x01'),
    ('UPC-A check digit transmitted', 0x24, 0x51, b'\x01'),
    ('UPC-E disabled', 0x24, 0x42, b'\x00'),
    ('EAN-13 enabled', 0x24, 0x43, b'\x01'),
    ('EAN-13 check digit transmitted', 0x24, 0x53, b'\x01'),
    ('EAN-8 enabled', 0x24, 0x44, b'\x01'),
    ('EAN-8 check digit transmitted', 0x24, 0x54, b'\x01'),
)

class AtomicBarcodeReader:

    def __init__(
        self,
        port: str,
        baudrate: int=115200,
        *,
        response_timeout: float=1.5,
        transport: SerialTransport | None=None
    ):
        if response_timeout <= 0:
            raise ValueError('response_timeout must be positive.')
        self.port = port
        self.baudrate = baudrate
        self.response_timeout = response_timeout
        self.transport = transport

    def open(self) -> None:
        if self.transport is not None:
            return
        try:
            import serial
        except ImportError as exc:
            raise ScannerError('pyserial not installed use: python -m pip install -r requirements.txt.') from exc
        device = serial.Serial(
            port=None,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            write_timeout=1.0,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
            exclusive=True
        )
        try:
            device.dtr = False
            device.rts = False
            device.port = self.port
            device.open()
        except Exception:
            device.close()
            raise
        self.transport = device

    def _serial(self) -> SerialTransport:
        if self.transport is None:
            raise ScannerError('Serial port is not open.')
        return self.transport

    def send_command(self, command: bytes) -> None:
        device = self._serial()
        if device.write(command) != len(command):
            raise ScannerError('Incomplete write.')
        device.flush()

    def _read_exact(self, count: int, deadline: float) -> bytes:
        data = bytearray()
        while len(data) < count and time.monotonic() < deadline:
            data.extend(self._serial().read(count - len(data)))
        if len(data) != count:
            raise ScannerError(f"Incomplete command reply: expected {count} bytes, but got {data.hex(' ')} instead.")
        return bytes(data)

    def _wait_header(self, header: bytes, deadline: float) -> None:
        seen = bytearray()
        while time.monotonic() < deadline and len(seen) < 4096:
            part = self._serial().read(1)
            if part:
                seen.extend(part)
                if seen.endswith(header):
                    return
        raise ScannerError(f"No reply header {header.hex(' ')} from {self.port}; received {bytes(seen[-64:]).hex(' ') or '(nothing)'}. Check UART wiring, power, baud rate and scanner interface mode.")

    def write_configuration(self, pid: int, fid: int, value: bytes) -> None:
        command = build_config_command(pid, fid, value)
        self.send_command(command)
        deadline = time.monotonic() + self.response_timeout
        self._wait_header(bytes([0x22, pid, fid]), deadline)
        reply = self._read_exact(2, deadline)
        expected_echo = value[0] if len(value) == 1 else 0
        if reply != bytes([expected_echo, 0]):
            raise ScannerError(f"Configuration rejected/unexpected reply for {command.hex(' ')}: {reply.hex(' ')}. Settings unlikely applied.")

    def read_configuration(self, pid: int, fid: int) -> bytes:
        self.send_command(bytes([0x23, pid, fid]))
        deadline = time.monotonic() + self.response_timeout
        self._wait_header(bytes([0x24, pid, fid]), deadline)
        width = fid >> 6
        if width == 3:
            width = int.from_bytes(self._read_exact(2, deadline), 'big')
            if width > 256:
                raise ScannerError('Unexpectedly configuration reply, possible mismatch.')
        return self._read_exact(width, deadline)

    def _control_with_reply(self, pid: int, fid: int, value: bytes=b'') -> None:
        self.send_command(bytes([0x32, pid, fid]) + value)
        deadline = time.monotonic() + self.response_timeout
        self._wait_header(bytes([0x33, pid, fid]), deadline)
        reply = self._read_exact(2, deadline)
        expected_echo = value[0] if len(value) == 1 else 0
        if reply != bytes([expected_echo, 0]):
            raise ScannerError(f"Control rejected/unexpected reply: {reply.hex(' ')}")

    def stop_decode(self) -> None:
        self._control_with_reply(117, 2)

    def configure_for_groceries(self, tell: Callable[[str], None]=LOG.info) -> None:
        self._serial().reset_input_buffer()
        name, pid, fid, value = GROCERY_PROFILE[0]
        self.write_configuration(pid, fid, value)
        self.stop_decode()
        tell(f'Configured: {name}')
        self._control_with_reply(118, 66, b'\x00')
        for name, pid, fid, value in GROCERY_PROFILE[1:]:
            self.write_configuration(pid, fid, value)
            tell(f'Configured: {name}')
        self.verify_configuration()
        tell('Configuration acknowledged. UPC-A, EAN-13 and EAN-8 should be good.')

    def verify_configuration(self) -> None:
        self._serial().reset_input_buffer()
        for name, pid, fid, expected in GROCERY_PROFILE:
            actual = self.read_configuration(pid, fid)
            if actual != expected:
                raise ScannerError(f"Scanner setting mismatch: {name}; expected {expected.hex() or '(empty)'}, got {actual.hex() or '(empty)'}.")

    def read_barcode(self, timeout: float=10.0, max_bytes: int=64, cancel: Event | None=None) -> str | None:
        if timeout <= 0:
            raise ValueError('Scan timeout must be positive value.')
        deadline = time.monotonic() + timeout
        data = bytearray()
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                raise ScanCancelled('Scan cancelled.')
            byte = self._serial().read(1)
            if not byte:
                continue
            data.extend(byte)
            if len(data) > max_bytes:
                raise ScannerError('Barcode frame too long: check settings.')
            if data.endswith(b'\r\n'):
                body = bytes(data[:-2])
                if not body:
                    data.clear()
                    continue
                try:
                    text = body.decode('ascii')
                except UnicodeDecodeError as exc:
                    raise ScannerError('Non-ASCII scan output. Check baud rate/output format for mismatch.') from exc
                if any((ord(char) < 32 or ord(char) > 126 for char in text)):
                    raise ScannerError('Control bytes inside barcode text. Check format.')
                return text
        if data:
            raise ScannerError(f'Incomplete scan (no terminator): {bytes(data)!r}.')
        return None

    def scan_once(self, timeout: float=10.0, cancel: Event | None=None) -> str | None:
        self._serial().reset_input_buffer()
        try:
            self.send_command(bytes.fromhex('32 75 01'))
            barcode = self.read_barcode(timeout, cancel=cancel)
        except BaseException:
            try:
                self.stop_decode()
            except Exception as exc:
                raise ScannerError('Unknown state, reboot and verify settings.') from exc
            raise
        self.stop_decode()
        return barcode

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None

    def __enter__(self) -> AtomicBarcodeReader:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
