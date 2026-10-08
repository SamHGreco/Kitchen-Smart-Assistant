"""
Raw HX711 communication driver.

Handles GPIO/bit-banging communication with the HX711 load cell amplifier
over its DOUT and SCK pins, returning raw integer readings. Conversion to 
grams (zero offset, scale factor) is handled separately in calibration.py. 
"""

import time
try:
    import RPi.GPIO as GPIO
except (ImportError, RuntimeError):
    GPIO = None


class HX711Driver:
    """Raw read/write access to a single HX711 chip over GPIO."""

    def __init__(self, dout_pin: int, sck_pin: int):
        self._dout_pin = dout_pin
        self._sck_pin = sck_pin
        self._ready = False

        if GPIO is None:
            raise RuntimeError("RPi.GPIO is not available; HX711Driver requires a Raspberry Pi.")

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._dout_pin, GPIO.IN)
        GPIO.setup(self._sck_pin, GPIO.OUT)
        GPIO.output(self._sck_pin, GPIO.LOW)


    def power_up(self) -> None:
            """Wakes the chip (pulse SCK low) per the HX711 datasheet."""
            GPIO.output(self._sck_pin, GPIO.LOW)

    def power_down(self) -> None:
         """Puts the chip to sleep (hold SCK high for >60us) per the HX711 datasheet."""
         GPIO.output(self._sck_pin, GPIO.HIGH)
         time.sleep(0.0001)  # Hold high for at least 60us, 100us margin for safety


    def raw_read(self) -> int:
         """
         Blocks until DOUT indicates data is ready, then clocks out a 24-bit 
         reading on SCK. Returns the signed raw value with no scaling applied.
         """
         timeout_seconds = 1.0
         start_time = time.time()
         while GPIO.input(self._dout_pin) == GPIO.HIGH:
             if time.time() - start_time > timeout_seconds:
                 raise TimeoutError("Timed out: HX711 did not signal data ready in time")
         
         raw_value = 0
         for i in range(24):
            GPIO.output(self._sck_pin, GPIO.HIGH)
            GPIO.output(self._sck_pin, GPIO.LOW)
            bit = GPIO.input(self._dout_pin)
            raw_value = (raw_value << 1) | bit

         # 25th pulse selects Channel A, gain 128 for the next conversion
         GPIO.output(self._sck_pin, GPIO.HIGH)
         GPIO.output(self._sck_pin, GPIO.LOW)
         
         if raw_value & 0x800000:
             raw_value -= 1 << 24

         return raw_value
    
