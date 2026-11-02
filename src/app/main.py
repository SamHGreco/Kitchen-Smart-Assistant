
"""Kitchen Smart Assistant application entry point.

Run on Raspberry Pi:
    python src/app/main.py --silent
    python src/app/main.py

Run without physical sensors (still requires a graphical desktop):
    python src/app/main.py --mockhardware

--silent disables the physical buzzer while retaining real sensor readings
and LED alarms. This is for development only, not a safety feature.
"""
from __future__ import annotations

import random
import time
import argparse
import logging
import sys
from pathlib import Path
import threading



SRC = Path(__file__).resolve().parents[1]
UI = SRC / "ui"

for directory in (SRC, UI):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from app import config
from app.shared.events import drain_events
from app.shared.models import ActivityType, UIState
from environment.alarm import AlarmController
from environment.environment_manager import EnvironmentManager
from environment.hardware.alarm_outputs import RealAlarmOutputDriver
from power.sleep_manager import PowerManager
from Sensor_Interfaces import TeamSensors
from Input_Validation import load_config
from ui.main import run_app
from Scale_Interface import ScaleReading
from scale.calibration import CalibrationParams
from scale.interface import HX711WeightSensor

logger = logging.getLogger(__name__)


class SilentAlarmOutputDriver(RealAlarmOutputDriver):
    """Preserve the physical alarm LED, but never energize the buzzer pin."""

    def set_buzzer(self, on: bool) -> None:
        # Initialize both pins as outputs LOW,
        # even if an alarm is already active.
        gpio = self._ensure_initialized()
        gpio.output(self._buzzer_pin, gpio.LOW)


def preload_hardware_libraries() -> None:
    """Avoid concurrent first imports of Blinka from sensor threads."""
    try:
        import board
        import busio
        import adafruit_dht
        import adafruit_ads1x15.ads1115
        import RPi.GPIO
    except ImportError as exc:
        logger.warning(
            "Hardware library preload incomplete: %s",
            exc
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kitchen Smart Assistant"
    )

    parser.add_argument(
        "--mockhardware",
        action="store_true",
        help="Use simulated sensor and alarm drivers"
    )

    parser.add_argument(
        "--silent",
        action="store_true",
        help="Keep physical buzzer off (development testing only)"
    )

    parser.add_argument(
        "--serial",
        action="store_true",
        help="Enable Bobby's serial barcode worker"
    )

    parser.add_argument(
        "--size",
        default="800x480",
        help="GUI size, e.g. 800x480"
    )

    parser.add_argument(
        "--fullscreen",
        action="store_true"
    )

    return parser.parse_args()


def build_scale_functions(scale_busy):
    """Connects the calibrated HX711 scale into the zero-argument
    read_scale/tare_scale callables PantryWindow expects. Returns
    (None, None) in mock-hardware mode."""
    if not config.HARDWARE_MODE:
        return None, None

    calibration = CalibrationParams(
        zero_offset=config.SCALE_ZERO_OFFSET,
        scale_factor=config.SCALE_SCALE_FACTOR,
    )
    sensor = HX711WeightSensor(
        dout_pin=config.SCALE_DOUT_PIN,
        sck_pin=config.SCALE_SCK_PIN,
        calibration=calibration,
    )

    def read_scale():
        scale_busy.set()
        time.sleep(3.0)
        try:
            max_attempts = 15
            required_agreement = 3
            tolerance = config.SCALE_SETTLE_THRESHOLD_G

            readings = []
            for _ in range(max_attempts):
                grams = sensor.read_weight()
                readings.append(grams)
                print(f"DEBUG sample {len(readings)}: {grams:.1f}g")
                time.sleep(0.05 + random.uniform(0, 0.15))

            clusters = []
            for value in readings:
                placed = False
                for cluster in clusters:
                    if abs(value - cluster[0]) <= tolerance:
                        cluster.append(value)
                        placed = True
                        break
                if not placed:
                    clusters.append([value])

            valid_clusters = [c for c in clusters if len(c) >= required_agreement]

            if valid_clusters:
                best = max(valid_clusters, key=lambda c: sum(c) / len(c))
                return ScaleReading(float(sum(best) / len(best)), True, time.time())

            return ScaleReading(float(max(readings)), False, time.time())
        finally:
            scale_busy.clear()

    def tare_scale():
        scale_busy.set()
        try:
            sensor.tare()
        finally:
            scale_busy.clear()

    return read_scale, tare_scale


def main() -> None:
    args = parse_args()

    if args.mockhardware:
        config.HARDWARE_MODE = False

    logging.basicConfig(
        level=config.LOG_LEVEL,
        format=config.LOG_FORMAT
    )

    logger.info(
        "Kitchen Smart Assistant starting (hardware=%s, silent=%s)",
        config.HARDWARE_MODE,
        args.silent
    )

    if config.HARDWARE_MODE:
        preload_hardware_libraries()

    power = PowerManager()

    alarm_controller = None

    if config.HARDWARE_MODE and args.silent:
        # Explicit driver injection.
        # Do not depend on BUZZER_ENABLED,
        # which the current alarm subsystem does not read.
        alarm_controller = AlarmController(
            driver=SilentAlarmOutputDriver(
                config.BUZZER_GPIO_PIN,
                config.ALARM_LED_GPIO_PIN
            )
        )

    environment = EnvironmentManager(
        power_manager=power,
        alarm_controller=alarm_controller,
    )

    sensors = TeamSensors(
        environment=environment,
        power=power,
        activity_type=ActivityType,
        ui_state=UIState,
    )


    settings = load_config(
        str(UI / "config.pi.json")
    )

    try:
        power.start()
        environment.start()
        
        scale_busy = threading.Event()
        read_scale, tare_scale = build_scale_functions(scale_busy)

        logger.info(
            "Subsystems started; launching GUI"
        )

        run_app(
            settings,
            demo=False,
            serial_enabled=args.serial,
            sensors=sensors,
            read_scale=read_scale,
            tare_scale=tare_scale,
            scale_busy=scale_busy,
            gas_calibration=environment,
            size=args.size,
            fullscreen=args.fullscreen,
            drain_events=drain_events,
        )

    except KeyboardInterrupt:
        logger.info(
            "Keyboard interrupt; exiting"
        )

    finally:
        logger.info(
            "Stopping subsystems"
        )

        environment.stop()
        power.stop()

        logger.info(
            "Shutdown complete"
        )


if __name__ == "__main__":
    main()
