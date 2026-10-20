import time
from datetime import datetime, timezone

from app.shared.models import SensorHealth
from environment.gas_calibration import GasCalibration, save_calibration
from environment.hardware.ads1115_driver import MockADS1115Driver
from environment.gas_sensor import GasMonitor


def _wait_until(predicate, timeout=2.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _make_monitor(driver, calibration_file_path=None):
    return GasMonitor(
        driver=driver,
        channel=0,
        poll_interval_seconds=0.02,
        max_consecutive_failures=3,
        alarm_threshold_voltage=1.5,
        alarm_hysteresis_voltage=0.15,
        alarm_debounce_seconds=0.1,
        filter_window=1,
        calibration_file_path=calibration_file_path,
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


def test_starts_uncalibrated_when_no_calibration_file(tmp_path):
    driver = MockADS1115Driver(baseline_voltage=0.4)
    monitor = _make_monitor(driver, calibration_file_path=tmp_path / "gas_calibration.json")

    assert monitor.is_calibrated() is False
    assert monitor.get_calibration() is None


def test_set_calibration_updates_threshold_via_existing_mechanism(tmp_path):
    driver = MockADS1115Driver(baseline_voltage=0.4)
    monitor = _make_monitor(driver, calibration_file_path=tmp_path / "gas_calibration.json")
    calibration = GasCalibration(
        gas_baseline_voltage=1.0,
        temperature_baseline_c=22.0,
        humidity_baseline_rh=45.0,
        calibration_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    monitor.set_calibration(calibration)

    assert monitor.is_calibrated() is True
    assert monitor.get_calibration() == calibration
    thresholds = monitor.get_alarm_thresholds()
    assert thresholds.threshold_voltage == 2.0  # 1.0V baseline * GAS_ALARM_MULTIPLIER (2.0)
    assert thresholds.hysteresis_voltage == 0.15, "hysteresis must be left unchanged by calibration"
    assert thresholds.debounce_seconds == 0.1, "debounce must be left unchanged by calibration"


def test_calibrated_alarm_trips_at_new_threshold(tmp_path):
    driver = MockADS1115Driver(baseline_voltage=0.4)
    monitor = _make_monitor(driver, calibration_file_path=tmp_path / "gas_calibration.json")
    monitor.set_calibration(
        GasCalibration(
            gas_baseline_voltage=1.0,
            temperature_baseline_c=22.0,
            humidity_baseline_rh=45.0,
            calibration_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    monitor.start()
    try:
        driver.simulate_gas_event(1.8)  # below the OLD 1.5V default, but below new 2.0V threshold too
        assert _wait_until(lambda: monitor.is_gas_alarm_active() is False, timeout=0.5)

        driver.simulate_gas_event(2.1)  # above the new calibrated 2.0V threshold
        assert _wait_until(lambda: monitor.is_gas_alarm_active() is True)
    finally:
        monitor.stop()


def test_loads_saved_calibration_at_construction(tmp_path):
    calibration_path = tmp_path / "gas_calibration.json"
    save_calibration(
        GasCalibration(
            gas_baseline_voltage=0.8,
            temperature_baseline_c=20.0,
            humidity_baseline_rh=40.0,
            calibration_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        calibration_path,
    )

    driver = MockADS1115Driver(baseline_voltage=0.4)
    monitor = _make_monitor(driver, calibration_file_path=calibration_path)

    assert monitor.is_calibrated() is True
    assert monitor.get_calibration().gas_baseline_voltage == 0.8
    assert monitor.get_alarm_thresholds().threshold_voltage == 1.6  # 0.8V * 2.0
