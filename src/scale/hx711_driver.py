"""
Raw HX711 communication driver.

Handles GPIO/bit-banging communication with the HX711 load cell amplifier
over its DOUT and SCK pins, returning raw integer readings. Conversion to 
grams (zero offset, scale factor) is handled separately in calibration.py. 
"""


class HX711Driver:
    """Raw read/write access to a single HX711 chip over GPIO."""

    def __init__(self, dout_pin: int, sck_pin: int):
        self._dout_pin = dout_pin
        self._sck_pin = sck_pin
        self._ready = False

        # TODO: configure GPIO for dout_pin/sck_pin once hardware is 
        # available, e.g.:
        #   import RPi.GPIO as GPIO
        #   GPIO.setmode(GPIO.BCM)
        #   GPIO.setup(self._dout_pin, GPIO.IN)
        #   GPIO.setup(self._sck_pin, GPIO.OUT)

    def power_up(self) -> None:
            """Wakes the chip (pulse SCK low) per the HX711 datasheet."""
            # TODO: implement wake sequence once hardware is available.
            raise NotImplementedError("HX711 power_up not implemented; requires physical hardware.")

    def power_down(self) -> None:
         """Puts the chip to sleep (hold SCK high for >60us) per the HX711 datasheet."""
         # TODO: implement sleep sequence once hardware is available.
         raise NotImplementedError("HX711 power_down not implemented; requires physical hardware.")

    def raw_read(self) -> int:
         """
         Blocks until DOUT indicates data is ready, then clocks out a 24-bit 
         reading on SCK. Returns the signed raw value with no scaling applied.
         """
         # TODO: implement the-bit clocked read and sign extension once hardware is available.
         raise NotImplementedError("HX711 raw_read not implemented; requires physical hardware.")
    
