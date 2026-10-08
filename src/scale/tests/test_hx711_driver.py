from __future__ import annotations

import pytest

from scale.hx711_driver import HX711Driver
import scale.hx711_driver as hx711_driver_module


class FakeGPIO:
    """Minimal GPIO stand-in that returns a scripted sequence of DOUT bits."""

    HIGH = 1
    LOW = 0
    BCM = "BCM"
    IN = "IN"
    OUT = "OUT"

    def __init__(self, bits: list[int] | None = None):
        self._bits = list(bits) if bits else []
        self._input_calls = 0
        self.output_calls: list[tuple[int, int]] = []

    def setmode(self, mode) -> None:
        pass

    def setup(self, pin, mode) -> None:
        pass

    def output(self, pin, value) -> None:
        self.output_calls.append((pin, value))

    def input(self, pin) -> int:
        self._input_calls += 1
        if self._input_calls == 1:
            return self.LOW          # first poll: report data ready immediately
        idx = self._input_calls - 2
        return self._bits[idx] if idx < len(self._bits) else 0


def bits_of(value: int, width: int = 24) -> list[int]:
    """MSB-first bit list for a given integer, for feeding into FakeGPIO."""
    return [(value >> i) & 1 for i in range(width - 1, -1, -1)]


@pytest.fixture
def fake_gpio(monkeypatch):
    """Replaces the real RPi.GPIO reference inside hx711_driver for one test."""
    def _install(bits=None):
        gpio = FakeGPIO(bits)
        monkeypatch.setattr(hx711_driver_module, "GPIO", gpio)
        return gpio
    return _install


def test_raw_read_positive_value(fake_gpio):
    fake_gpio(bits_of(0x010203))
    driver = HX711Driver(dout_pin=5, sck_pin=6)
    assert driver.raw_read() == 0x010203


def test_raw_read_all_ones_is_negative_one(fake_gpio):
    fake_gpio(bits_of(0xFFFFFF))
    driver = HX711Driver(dout_pin=5, sck_pin=6)
    assert driver.raw_read() == -1


def test_raw_read_sign_bit_set_is_negative(fake_gpio):
    raw_bits_value = 0x800001
    fake_gpio(bits_of(raw_bits_value))
    driver = HX711Driver(dout_pin=5, sck_pin=6)
    assert driver.raw_read() == raw_bits_value - (1 << 24)


def test_raw_read_zero(fake_gpio):
    fake_gpio(bits_of(0))
    driver = HX711Driver(dout_pin=5, sck_pin=6)
    assert driver.raw_read() == 0


def test_power_up_sets_clock_pin_low(fake_gpio):
    gpio = fake_gpio()
    driver = HX711Driver(dout_pin=5, sck_pin=6)
    gpio.output_calls.clear()
    driver.power_up()
    assert (6, gpio.LOW) in gpio.output_calls


def test_power_down_sets_clock_pin_high(fake_gpio):
    gpio = fake_gpio()
    driver = HX711Driver(dout_pin=5, sck_pin=6)
    gpio.output_calls.clear()
    driver.power_down()
    assert (6, gpio.HIGH) in gpio.output_calls


def test_init_raises_without_gpio_available(monkeypatch):
    monkeypatch.setattr(hx711_driver_module, "GPIO", None)
    with pytest.raises(RuntimeError):
        HX711Driver(dout_pin=5, sck_pin=6)