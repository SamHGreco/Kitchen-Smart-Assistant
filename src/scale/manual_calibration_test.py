"""
Manual calibration and verification script for the HX711 scale.

Run directly on the Raspberry Pi with the scale wired up.
Averages several raw readings to find a zero baseline, waits for
user to place known weight, averages again, calibrates, then
prints live weight in grams.
"""

import time

from scale.hx711_driver import HX711Driver
from scale.calibration import calibrate_from_known_weight
from scale.interface import HX711WeightSensor

DOUT_PIN = 5
SCK_PIN = 6
SAMPLES = 10
KNOWN_WEIGHT_GRAMS = 120.0 # update to actual reference weight


def average_reading(driver: HX711Driver, samples: int = SAMPLES) -> float:
    readings = []
    for _ in range(samples):
        readings.append(driver.raw_read())
        time.sleep(0.1)
    return sum(readings) / len(readings)


def main() -> None:
    driver = HX711Driver (dout_pin=DOUT_PIN, sck_pin=SCK_PIN)

    input("Ensure scale has nothing on it, then press Enter...")
    raw_zero = average_reading(driver)
    print(f"Zero baseline: {raw_zero:.1f}")

    input(f"Place your {KNOWN_WEIGHT_GRAMS}g reference weight on the scale, "
        "let it stabilize, then press Enter...")
    raw_loaded = average_reading(driver)
    print(f"Loaded reading: {raw_loaded:.1f}")

    params = calibrate_from_known_weight(
        raw_zero=round(raw_zero),
        raw_with_known_weight=round(raw_loaded),
        known_weight_grams=KNOWN_WEIGHT_GRAMS,
    )
    print(f"Calibration: zero_offset={params.zero_offset}, "
        f"scale_factor={params.scale_factor:.4f}")

    sensor = HX711WeightSensor(dout_pin=DOUT_PIN, sck_pin=SCK_PIN, calibration=params)
    # No need to call sensor.tare() here, the calibration's zero_offset
    # already captures the no-load baseline.

    print("\n Printing live grams now, Ctrl+C to stop.\n")    #averaged over 5 samples each)
    try:
        while True:
                grams = sensor.read_stable_weight()
                print(f"{grams:.1f} g")
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
