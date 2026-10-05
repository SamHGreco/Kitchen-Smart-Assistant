"""Application entry point.

Wires up and runs the Environment / Safety / Power subsystem (mine). Bobby's
touchscreen GUI and Jamie's scale/inventory subsystem are not implemented
yet, so their startup code is left as TODO placeholders below - see the "Data Bobby/Jamie need" integration points.

Run:
    python src/app/main.py

Uses real hardware drivers by default (HARDWARE_MODE=True), for running on
the Raspberry Pi with the sensors wired up. To develop/test on a machine
without the Pi/sensors attached, either pass --mockhardware or set the
KSA_HARDWARE_MODE=0 environment variable:

    python src/app/main.py --mockhardware
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# This file lives at src/app/main.py, so `parents[1]` is `src` itself.
_SRC_DIR = Path(__file__).resolve().parents[1]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from app import config  # noqa: E402
from environment.environment_manager import EnvironmentManager  # noqa: E402
from power.sleep_manager import PowerManager  # noqa: E402

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 5.0


def build_subsystem() -> tuple[EnvironmentManager, PowerManager]:
    """Construct the real environment/safety/power objects, wired together.

    Driver selection (real vs. mock) is decided inside each module from
    config.HARDWARE_MODE - this function does not choose drivers itself.
    """
    power_manager = PowerManager()
    environment_manager = EnvironmentManager(power_manager=power_manager)
    return environment_manager, power_manager


def _log_heartbeat(environment_manager: EnvironmentManager, power_manager: PowerManager) -> None:
    status = environment_manager.get_status()
    logger.info(
        "status: temp=%sC humidity=%s%% gas_alarm=%s temp_alarm=%s humidity_alarm=%s "
        "motion=%s safety=%s display_awake=%s",
        status.temperature_c,
        status.humidity_percent,
        status.gas_alarm,
        status.temp_alarm,
        status.humidity_alarm,
        status.motion_detected,
        status.safety_state.name,
        power_manager.is_display_awake(),
    )


def _preload_hardware_libraries() -> None:
    """Import hardware libraries once, in the main thread, before any sensor
    threads start.

    adafruit-blinka's `board` module is not safe to import for the first
    time from multiple threads concurrently - EnvironmentManager starts the
    DHT11/gas/PIR monitor threads nearly simultaneously, and each driver
    lazily imports `board`/`busio`/etc. on first use, which can deadlock
    inside adafruit_platformdetect if two threads race to import it at once.
    Importing here first means every later lazy import just hits Python's
    module cache instead of racing to load it.
    """
    try:
        import board  # noqa: F401
        import busio  # noqa: F401
        import adafruit_dht  # noqa: F401
        import adafruit_ads1x15.ads1115  # noqa: F401
        import RPi.GPIO  # noqa: F401
    except ImportError as exc:
        logger.warning("Hardware library preload skipped (%s) - sensors will report FAULT", exc)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Environment/Safety/Power subsystem entry point")
    parser.add_argument(
        "--mockhardware",
        action="store_true",
        help="Use mock hardware drivers for this run instead of real sensors/GPIO (overrides KSA_HARDWARE_MODE)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.mockhardware:
        config.HARDWARE_MODE = False

    logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
    logger.info("Kitchen Smart Assistant - Environment/Safety/Power subsystem starting")
    logger.info("HARDWARE_MODE=%s", config.HARDWARE_MODE)
    if config.HARDWARE_MODE:
        logger.info(
            "GPIO/I2C wiring: DHT11=GPIO%s PIR=GPIO%s BUZZER=GPIO%s LED=GPIO%s ADS1115=0x%02X channel=%s",
            config.DHT11_GPIO_PIN,
            config.PIR_GPIO_PIN,
            config.BUZZER_GPIO_PIN,
            config.ALARM_LED_GPIO_PIN,
            config.ADS1115_I2C_ADDRESS,
            config.ADS1115_GAS_CHANNEL,
        )
        _preload_hardware_libraries()

    environment_manager, power_manager = build_subsystem()

    # TODO: Bobby's UI subsystem - construct/run the touchscreen GUI here.
    # It should poll environment_manager.get_status() and
    # app.shared.events.drain_events(), and call
    # power_manager.notify_activity()/set_ui_state()/set_transaction_active().

    # TODO: Jamie's scale/inventory subsystem - start scale polling here,
    # calling power_manager.notify_activity(ActivityType.WEIGHT) on load changes.

    power_manager.start()
    environment_manager.start()

    last_heartbeat = time.monotonic()
    try:
        # No GUI mainloop exists yet, so just idle and log a periodic status
        # heartbeat. Once Bobby's GUI exists, its mainloop replaces this.
        while True:
            time.sleep(1.0)
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                _log_heartbeat(environment_manager, power_manager)
                last_heartbeat = now
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received - shutting down")
    finally:
        environment_manager.stop()
        power_manager.stop()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
