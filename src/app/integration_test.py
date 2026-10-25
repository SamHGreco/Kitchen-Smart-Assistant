
"""Initial Bobby + Sam integration test using mock sensors."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
UI = SRC / "ui"

for directory in (SRC, UI):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from app import config

# Select mock drivers before constructing the subsystem.
config.HARDWARE_MODE = False

from app.shared.models import ActivityType, UIState
from environment.environment_manager import EnvironmentManager
from power.sleep_manager import PowerManager
from Sensor_Interfaces import TeamSensors
from Input_Validation import load_config
from main import run_app


def main():
    power = PowerManager()
    environment = EnvironmentManager(power_manager=power)

    sensors = TeamSensors(
        environment=environment,
        power=power,
        activity_type=ActivityType,
        ui_state=UIState,
    )

    settings = load_config(str(UI / "config.pi.json"))

    try:
        power.start()
        environment.start()

        run_app(
            settings,
            demo=False,
            serial_enabled=False,
            sensors=sensors,
            size="800x480",
        )

    finally:
        environment.stop()
        power.stop()


if __name__ == "__main__":
    main()
