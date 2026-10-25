# Stand in for now


from __future__ import annotations
import time
from types import SimpleNamespace


class HX711Raw:
    def __init__(self, data_pin=5, clock_pin=6, *, chip=0):
        import lgpio
        self.gpio = lgpio
        self.data_pin, self.clock_pin = data_pin, clock_pin
        self.handle = lgpio.gpiochip_open(chip)
        self.claimed = []
        try:
            lgpio.gpio_claim_input(self.handle, data_pin)
            self.claimed.append(data_pin)
            lgpio.gpio_claim_output(self.handle, clock_pin, 0)
            self.claimed.append(clock_pin)
            self._reset()
        except BaseException:
            self.close()
            raise

    def _reset(self):
        self.gpio.gpio_write(self.handle, self.clock_pin, 1)
        time.sleep(0.001)
        self.gpio.gpio_write(self.handle, self.clock_pin, 0)
        time.sleep(0.5)

    def _pulse(self) -> int:
        started = time.perf_counter_ns()
        try:
            self.gpio.gpio_write(self.handle, self.clock_pin, 1)
            until = time.perf_counter_ns() + 1000
            while time.perf_counter_ns() < until:
                pass
            bit = self.gpio.gpio_read(self.handle, self.data_pin)
        finally:
            self.gpio.gpio_write(self.handle, self.clock_pin, 0)
        if time.perf_counter_ns() - started > 50000:
            raise RuntimeError('HX711 clock timing overrun.')
        return bit

    def read_raw(self, samples=9, timeout=3.0) -> list[int]:
        if type(samples) is not int or not 1 <= samples <= 100 or not 0 < timeout <= 30:
            raise ValueError('Invalid scale sample count or timeout.')
        deadline = time.monotonic() + timeout
        result = []
        try:
            for _ in range(samples):
                while self.gpio.gpio_read(self.handle, self.data_pin):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('HX711 not ready.')
                    time.sleep(0.001)
                if time.monotonic() >= deadline:
                    raise TimeoutError('HX711 timed out.')
                value = 0
                for _ in range(24):
                    value = (value << 1) | self._pulse()
                self._pulse()
                if not self.gpio.gpio_read(self.handle, self.data_pin):
                    raise RuntimeError('HX711 DOUT low after conversion.')
                result.append(value - 0x1000000 if value & 0x800000 else value)
            return result
        except Exception:
            self._reset()
            raise

    def close(self):
        if self.handle is None:
            return
        try:
            if self.clock_pin in self.claimed:
                self.gpio.gpio_write(self.handle, self.clock_pin, 0)
            for pin in self.claimed:
                self.gpio.gpio_free(self.handle, pin)
        finally:
            self.gpio.gpiochip_close(self.handle)
            self.handle = None


class PIRInput:
    def __init__(self, pin, *, factory, error_type=RuntimeError):
        from gpiozero import DigitalInputDevice
        self.device = DigitalInputDevice(pin, pull_up=False, pin_factory=factory)
        self.error_type = error_type

    def read(self) -> bool:
        try:
            return bool(self.device.value)
        except Exception as exc:
            raise self.error_type(f'PIR read failed: {exc}') from exc

    def close(self):
        self.device.close()


class AlarmOutputs:
    def __init__(self, buzzer_pin, led_pin, *, factory,
                 buzzer_active_high=True, led_active_high=True):
        from gpiozero import OutputDevice
        self.buzzer = OutputDevice(buzzer_pin, active_high=buzzer_active_high,
                                   initial_value=False, pin_factory=factory)
        try:
            self.led = OutputDevice(led_pin, active_high=led_active_high,
                                    initial_value=False, pin_factory=factory)
        except BaseException:
            self.buzzer.close()
            raise

    def set_buzzer(self, on: bool):
        self.buzzer.value = bool(on)

    def set_led(self, on: bool):
        self.led.value = bool(on)

    def close(self):
        if self.buzzer.closed:
            return
        try:
            self.buzzer.off()
            self.led.off()
        finally:
            self.buzzer.close()
            self.led.close()


class DHTInput:
    def __init__(self, pin, *, error_type=RuntimeError):
        import adafruit_dht
        import board
        self.device = adafruit_dht.DHT11(getattr(board, f'D{pin}'), use_pulseio=False)
        self.error_type = error_type

    def read(self):
        try:
            temperature, humidity = self.device.temperature, self.device.humidity
            if temperature is None or humidity is None:
                raise ValueError('Incomplete DHT reading')
            return SimpleNamespace(temperature_c=temperature, humidity_percent=humidity)
        except Exception as exc:
            raise self.error_type(f'DHT11 read failed: {exc}') from exc

    def close(self):
        if self.device is not None:
            self.device.exit()
            self.device = None


class ADSInput:
    def __init__(self, address=0x48, *, error_type=RuntimeError):
        import board
        from adafruit_ads1x15.ads1115 import ADS1115
        self.i2c = board.I2C()
        try:
            self.adc = ADS1115(self.i2c, address=address, gain=1)
        except BaseException:
            self.i2c.deinit()
            raise
        self.channels = {}
        self.raw = {}
        self.error_type = error_type

    def _sample(self, channel):
        try:
            from adafruit_ads1x15.analog_in import AnalogIn
            if type(channel) is not int or not 0 <= channel <= 3:
                raise ValueError('ADS1115 channel error.')
            if channel not in self.channels:
                self.channels[channel] = AnalogIn(self.adc, channel)
            self.raw[channel] = int(self.channels[channel].value)
            return self.raw[channel]
        except Exception as exc:
            raise self.error_type(f'ADS1115 read failed: {exc}') from exc

    def read_voltage(self, channel):
        return self._sample(channel) * (4.096 / 32768)

    def read_raw(self, channel):
        return self.raw[channel] if channel in self.raw else self._sample(channel)

    def close(self):
        self.channels.clear()
        if self.i2c is not None:
            self.i2c.deinit()
            self.i2c = None
