import time

from app.shared.events import drain_events
from app.shared.models import SafetyState
from environment.alarm import AlarmController
from environment.environment_manager import EnvironmentManager
from environment.gas_sensor import GasMonitor
from environment.hardware.ads1115_driver import MockADS1115Driver
from environment.hardware.alarm_outputs import MockAlarmOutputDriver
from environment.hardware.dht11_driver import MockDHT11Driver
from environment.hardware.pir_driver import MockPIRDriver
from environment.motion import MotionMonitor
from environment.temperature_humidity import TemperatureHumidityMonitor


def _wait_until(predicate, timeout=2.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _make_manager():
    gas_driver = MockADS1115Driver(baseline_voltage=0.4)
    pir_driver = MockPIRDriver()
    alarm_driver = MockAlarmOutputDriver()

    manager = EnvironmentManager(
        temperature_humidity_monitor=TemperatureHumidityMonitor(
            driver=MockDHT11Driver(), poll_interval_seconds=0.02
        ),
        gas_monitor=GasMonitor(
            driver=gas_driver,
            poll_interval_seconds=0.02,
            alarm_threshold_voltage=1.5,
            alarm_hysteresis_voltage=0.15,
            alarm_debounce_seconds=0.05,
            filter_window=1,
        ),
        motion_monitor=MotionMonitor(driver=pir_driver, poll_interval_seconds=0.02, debounce_seconds=0.05),
        alarm_controller=AlarmController(driver=alarm_driver),
        poll_interval_seconds=0.02,
    )
    return manager, gas_driver, pir_driver, alarm_driver


def test_normal_status_when_all_sensors_ok():
    manager, _gas_driver, _pir_driver, _alarm_driver = _make_manager()
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_status().safety_state == SafetyState.NORMAL)
    finally:
        manager.stop()


def test_gas_alarm_drives_alarm_outputs_and_safety_state():
    manager, gas_driver, _pir_driver, alarm_driver = _make_manager()
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_status().safety_state == SafetyState.NORMAL)
        gas_driver.simulate_gas_event(2.0)
        assert _wait_until(lambda: manager.is_gas_alarm_active() is True)
        assert manager.get_status().safety_state == SafetyState.ALARM
        assert alarm_driver.buzzer_on is True
        assert alarm_driver.led_on is True
    finally:
        manager.stop()


def test_motion_and_gas_alarm_publish_events():
    manager, gas_driver, pir_driver, _alarm_driver = _make_manager()
    manager.start()
    try:
        pir_driver.trigger_motion(True)
        assert _wait_until(lambda: manager.is_motion_detected() is True)
        events = drain_events()
        assert any(e.event_type.name == "MOTION_DETECTED" for e in events)

        gas_driver.simulate_gas_event(2.0)
        assert _wait_until(lambda: manager.is_gas_alarm_active() is True)
        events = drain_events()
        assert any(e.event_type.name == "GAS_ALARM_STARTED" for e in events)

        gas_driver.simulate_gas_event(0.4)
        assert _wait_until(lambda: manager.is_gas_alarm_active() is False)
        events = drain_events()
        assert any(e.event_type.name == "GAS_ALARM_CLEARED" for e in events)
    finally:
        manager.stop()
