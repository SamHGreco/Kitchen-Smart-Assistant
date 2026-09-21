import time

from app.shared.models import SensorHealth
from environment.hardware.ads1115_driver import MockADS1115Driver
from environment.gas_sensor import GasMonitor


def _wait_until(predicate, timeout=2.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _make_monitor(driver):
    return GasMonitor(
        driver=driver,
        channel=0,
        poll_interval_seconds=0.02,
        max_consecutive_failures=3,
        alarm_threshold_voltage=1.5,
        alarm_hysteresis_voltage=0.15,
        alarm_debounce_seconds=0.1,
        filter_window=1,
    )


def test_no_alarm_at_baseline():
    driver = MockADS1115Driver(baseline_voltage=0.4)
    monitor = _make_monitor(driver)
    monitor.start()
    try:
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.OK)
        assert monitor.is_gas_alarm_active() is False
    finally:
        monitor.stop()


def test_alarm_requires_debounce_then_trips():
    driver = MockADS1115Driver(baseline_voltage=0.4)
    monitor = _make_monitor(driver)
    monitor.start()
    try:
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.OK)
        driver.simulate_gas_event(2.0)
        # Immediately after the spike, debounce should not have elapsed yet.
        time.sleep(0.03)
        assert monitor.is_gas_alarm_active() is False
        assert _wait_until(lambda: monitor.is_gas_alarm_active() is True)
    finally:
        monitor.stop()


def test_hysteresis_prevents_chatter_near_threshold():
    driver = MockADS1115Driver(baseline_voltage=0.4)
    monitor = _make_monitor(driver)
    monitor.start()
    try:
        driver.simulate_gas_event(2.0)
        assert _wait_until(lambda: monitor.is_gas_alarm_active() is True)

        # Between threshold (1.5) and threshold-hysteresis (1.35) - should stay latched.
        driver.simulate_gas_event(1.4)
        time.sleep(0.3)
        assert monitor.is_gas_alarm_active() is True

        driver.simulate_gas_event(1.0)
        assert _wait_until(lambda: monitor.is_gas_alarm_active() is False)
    finally:
        monitor.stop()


def test_fault_freezes_alarm_state_instead_of_clearing_it():
    driver = MockADS1115Driver(baseline_voltage=0.4)
    monitor = _make_monitor(driver)
    monitor.start()
    try:
        driver.simulate_gas_event(2.0)
        assert _wait_until(lambda: monitor.is_gas_alarm_active() is True)

        driver.force_failure(True)
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.FAULT)
        reading = monitor.get_reading()
        assert reading.gas_raw is None
        assert reading.gas_voltage is None
        assert reading.gas_alarm is True, "a real alarm must not be cleared by a sensor fault"
    finally:
        monitor.stop()
