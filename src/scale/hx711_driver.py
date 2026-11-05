"""HX711 GPIO reader with bounded waits and timing-overrun rejection.

This remains Linux/Python bit-banging, NOT a real-time timing guarantee.
Repeated clock overruns require a hardware-timed or microcontroller backend.
"""
from __future__ import annotations
import time

try:
    import RPi.GPIO as GPIO
except (ImportError, RuntimeError):
    GPIO = None


class ClockTimingError(RuntimeError):
    pass


class HX711Driver:
    def __init__(self, dout_pin: int, sck_pin: int):
        if GPIO is None:
            raise RuntimeError('RPi.GPIO unavailable; use a Raspberry Pi 4.')
        if dout_pin == sck_pin:
            raise ValueError('DOUT and SCK must be different pins.')
        self._dout_pin = dout_pin
        self._sck_pin = sck_pin
        self._closed = False
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(dout_pin, GPIO.IN)
        GPIO.setup(sck_pin, GPIO.OUT)
        GPIO.output(sck_pin, GPIO.LOW)

    def power_up(self):
        GPIO.output(self._sck_pin, GPIO.LOW)

    def power_down(self):
        GPIO.output(self._sck_pin, GPIO.HIGH)
        time.sleep(0.0001)

    def _reset(self):
        try:
            self.power_down()
        finally:
            self.power_up()
        # HX711 settling time after reset at RATE=0 (10 samples/sec).
        time.sleep(0.4)

    def _pulse(self, read_bit=True):
        started = time.perf_counter_ns()
        bit = 0
        try:
            GPIO.output(self._sck_pin, GPIO.HIGH)
            until = time.perf_counter_ns() + 1000
            while time.perf_counter_ns() < until:
                pass
            if read_bit:
                bit = GPIO.input(self._dout_pin)
        finally:
            GPIO.output(self._sck_pin, GPIO.LOW)
        # Conservative measurement includes GPIO call overhead. Reject rather
        # than reporting a plausible-looking value after a stretched pulse.
        if time.perf_counter_ns() - started > 50000:
            raise ClockTimingError('HX711 clock timing overrun; sample discarded.')
        until = time.perf_counter_ns() + 1000
        while time.perf_counter_ns() < until:
            pass
        return bit

    def raw_read(self, retries=3, timeout_seconds=1.0):
        if self._closed:
            raise RuntimeError('Scale driver is closed.')
        if type(retries) is not int or retries < 1 or timeout_seconds <= 0:
            raise ValueError('Invalid retry count or timeout.')
        for attempt in range(retries):
            try:
                return self._raw_read_once(timeout_seconds)
            except (TimeoutError, ClockTimingError):
                self._reset()
                if attempt == retries - 1:
                    raise

    def _raw_read_once(self, timeout_seconds=1.0):
        deadline = time.monotonic() + timeout_seconds
        while GPIO.input(self._dout_pin) == GPIO.HIGH:
            if time.monotonic() >= deadline:
                raise TimeoutError('HX711 not ready. Check DOUT/SCK, voltage and ground.')
            time.sleep(0.001)
        value = 0
        for _ in range(24):
            value = (value << 1) | self._pulse()
        self._pulse(read_bit=False)  # 25 pulses: channel A, gain 128.
        return value - (1 << 24) if value & 0x800000 else value

    def close(self):
        if self._closed:
            return
        try:
            GPIO.output(self._sck_pin, GPIO.LOW)
            GPIO.cleanup((self._dout_pin, self._sck_pin))
        finally:
            self._closed = True
