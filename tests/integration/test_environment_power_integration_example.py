"""Phase 10 integration example: how Bobby's GUI and Jamie's scale subsystem
would talk to the environment/safety/power subsystem, without depending on
any of their real implementations. Bobby's and Jamie's code is stood in for
here with tiny mock stubs that only call the public API documented for them.

Run directly (`python tests/integration/test_environment_power_integration_example.py`)
or via pytest - both work, since it's also a normal pytest test.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.shared.events import drain_events  # noqa: E402
from app.shared.models import ActivityType, UIState  # noqa: E402
from environment.alarm import AlarmController  # noqa: E402
from environment.environment_manager import EnvironmentManager  # noqa: E402
from environment.gas_sensor import GasMonitor  # noqa: E402
from environment.hardware.ads1115_driver import MockADS1115Driver  # noqa: E402
from environment.hardware.alarm_outputs import MockAlarmOutputDriver  # noqa: E402
from environment.hardware.dht11_driver import MockDHT11Driver  # noqa: E402
from environment.hardware.pir_driver import MockPIRDriver  # noqa: E402
from environment.motion import MotionMonitor  # noqa: E402
from environment.temperature_humidity import TemperatureHumidityMonitor  # noqa: E402
from power.sleep_manager import PowerManager  # noqa: E402


class FakeScaleSubsystem:
    """Stands in for Jamie's real scale subsystem.

    Jamie's actual code just needs to call `power_manager.notify_activity()`
    whenever the load cell sees a weight change - it never touches
    environment/power internals directly.
    """

    def __init__(self, power_manager: PowerManager) -> None:
        self._power_manager = power_manager

    def simulate_item_placed_on_scale(self) -> None:
        self._power_manager.notify_activity(ActivityType.WEIGHT)


class FakeGuiSubsystem:
    """Stands in for Bobby's real GUI/touchscreen subsystem.

    Bobby's actual code polls `EnvironmentManager.get_status()` for display
    data, drains `app.shared.events` for alarm/motion notifications, and
    reports its own state back via `PowerManager.set_ui_state()` /
    `set_transaction_active()` / `notify_activity(ActivityType.TOUCH)`.
    """

    def __init__(self, environment: EnvironmentManager, power_manager: PowerManager) -> None:
        self._environment = environment
        self._power_manager = power_manager
        self.received_events: list[str] = []

    def render_frame(self) -> None:
        status = self._environment.get_status()
        for event in drain_events():
            self.received_events.append(event.event_type.value)
        if status.gas_alarm:
            pass  # Bobby's real GUI would show an alarm banner here.

    def user_taps_screen(self) -> None:
        self._power_manager.notify_activity(ActivityType.TOUCH)

    def start_inventory_transaction(self) -> None:
        self._power_manager.set_transaction_active(True)

    def finish_inventory_transaction(self) -> None:
        self._power_manager.set_transaction_active(False)

    def navigate_to(self, ui_state: UIState) -> None:
        self._power_manager.set_ui_state(ui_state)


def _wait_until(predicate, timeout=2.0, interval=0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_gui_and_scale_integration_example():
    gas_driver = MockADS1115Driver(baseline_voltage=0.4)

    power_manager = PowerManager(inactivity_timeout_seconds=0.3, poll_interval_seconds=0.02)
    environment = EnvironmentManager(
        temperature_humidity_monitor=TemperatureHumidityMonitor(
            driver=MockDHT11Driver(), poll_interval_seconds=0.02
        ),
        gas_monitor=GasMonitor(
            driver=gas_driver,
            poll_interval_seconds=0.02,
            alarm_debounce_seconds=0.05,
            filter_window=1,
        ),
        motion_monitor=MotionMonitor(driver=MockPIRDriver(), poll_interval_seconds=0.02),
        alarm_controller=AlarmController(driver=MockAlarmOutputDriver()),
        power_manager=power_manager,
        poll_interval_seconds=0.02,
    )

    gui = FakeGuiSubsystem(environment, power_manager)
    scale = FakeScaleSubsystem(power_manager)

    power_manager.start()
    environment.start()
    try:
        # Bobby's GUI starts on the home screen.
        gui.navigate_to(UIState.HOME)

        # Jamie's scale reports a weight change - display must wake and stay awake.
        scale.simulate_item_placed_on_scale()
        assert power_manager.is_display_awake() is True

        # Idle on the home screen long enough -> display should sleep.
        assert _wait_until(lambda: power_manager.is_display_awake() is False)

        # A gas alarm must wake the display immediately even while idle.
        gas_driver.simulate_gas_event(2.0)
        assert _wait_until(lambda: environment.is_gas_alarm_active() is True)
        gui.render_frame()
        assert power_manager.is_display_awake() is True
        assert "gas_alarm_started" in gui.received_events

        # An active inventory transaction must block sleep even if idle.
        gas_driver.simulate_gas_event(0.4)
        assert _wait_until(lambda: environment.is_gas_alarm_active() is False)
        gui.start_inventory_transaction()
        time.sleep(0.5)
        assert power_manager.is_display_awake() is True
        gui.finish_inventory_transaction()
    finally:
        environment.stop()
        power_manager.stop()


if __name__ == "__main__":
    test_gui_and_scale_integration_example()
    print("Integration example passed.")
