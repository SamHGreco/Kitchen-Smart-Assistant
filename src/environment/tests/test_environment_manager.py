import time
from datetime import datetime, timezone

import pytest

from app.shared.events import drain_events
from app.shared.models import SafetyState, SensorHealth
from environment.alarm import AlarmController
from environment.environment_manager import EnvironmentManager
from environment.gas_sensor import GasMonitor
from environment.hardware.ads1115_driver import MockADS1115Driver
from environment.hardware.alarm_outputs import MockAlarmOutputDriver
from environment.hardware.dht11_driver import MockDHT11Driver
from environment.hardware.pir_driver import MockPIRDriver
from environment.motion import MotionMonitor
from environment.temperature_humidity import TemperatureHumidityMonitor, TemperatureHumidityReading


def _wait_until(predicate, timeout=2.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _FixedTemperatureHumidityMonitor:
    """Deterministic (no sensor jitter) stand-in for precise boundary tests."""

    def __init__(self, temperature_c: float = 22.0, humidity_percent: float = 45.0) -> None:
        self.temperature_c = temperature_c
        self.humidity_percent = humidity_percent

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def get_reading(self) -> TemperatureHumidityReading:
        return TemperatureHumidityReading(
            temperature_c=self.temperature_c,
            humidity_percent=self.humidity_percent,
            temp_alarm=False,
            humidity_alarm=False,
            health=SensorHealth.OK,
            timestamp=datetime.now(timezone.utc),
        )

    def get_temperature_c(self) -> float | None:
        return self.temperature_c

    def get_humidity_percent(self) -> float | None:
        return self.humidity_percent


def _make_manager(calibration_file_path=None, dht_driver=None, temperature_humidity_monitor=None):
    gas_driver = MockADS1115Driver(baseline_voltage=0.4)
    pir_driver = MockPIRDriver()
    alarm_driver = MockAlarmOutputDriver()
    dht_driver = dht_driver if dht_driver is not None else MockDHT11Driver()
    temp_monitor = (
        temperature_humidity_monitor
        if temperature_humidity_monitor is not None
        else TemperatureHumidityMonitor(driver=dht_driver, poll_interval_seconds=0.02)
    )

    manager = EnvironmentManager(
        temperature_humidity_monitor=temp_monitor,
        gas_monitor=GasMonitor(
            driver=gas_driver,
            poll_interval_seconds=0.02,
            alarm_threshold_voltage=1.5,
            alarm_hysteresis_voltage=0.15,
            alarm_debounce_seconds=0.05,
            filter_window=1,
            calibration_file_path=calibration_file_path,
        ),
        motion_monitor=MotionMonitor(driver=pir_driver, poll_interval_seconds=0.02, debounce_seconds=0.05),
        alarm_controller=AlarmController(driver=alarm_driver),
        poll_interval_seconds=0.02,
    )
    return manager, gas_driver, pir_driver, alarm_driver, dht_driver


def test_normal_status_when_all_sensors_ok():
    manager, _gas_driver, _pir_driver, _alarm_driver, _dht_driver = _make_manager()
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_status().safety_state == SafetyState.NORMAL)
    finally:
        manager.stop()


def test_gas_alarm_drives_alarm_outputs_and_safety_state():
    manager, gas_driver, _pir_driver, alarm_driver, _dht_driver = _make_manager()
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
    manager, gas_driver, pir_driver, _alarm_driver, _dht_driver = _make_manager()
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


# ============================================================
# GAS CALIBRATION
# ============================================================


def test_not_calibrated_status_before_any_calibration(tmp_path):
    manager, _gas_driver, _pir_driver, _alarm_driver, _dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    try:
        manager.start()
        assert _wait_until(lambda: manager.get_temperature_c() is not None)

        status = manager.get_gas_calibration_status()

        assert status.is_calibrated is False
        assert status.baseline_voltage is None
        assert status.recalibration_needed is False
        assert status.recalibration_reasons == ()
        assert status.calibration_timestamp is None
    finally:
        manager.stop()


def test_calibrate_gas_sensor_success_records_current_readings(tmp_path):
    manager, gas_driver, _pir_driver, _alarm_driver, dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    gas_driver.simulate_gas_event(0.6)
    dht_driver._baseline_temperature_c = 25.0
    dht_driver._baseline_humidity_percent = 50.0
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        assert _wait_until(lambda: manager.get_gas_status().gas_voltage == pytest.approx(0.6, abs=0.1))

        result = manager.calibrate_gas_sensor()

        assert result.success is True
        assert result.status.is_calibrated is True
        assert result.status.baseline_voltage == pytest.approx(0.6, abs=0.1)
        assert result.status.temperature_baseline_c == pytest.approx(25.0, abs=0.6)
        assert result.status.humidity_baseline_rh == pytest.approx(50.0, abs=2.5)
        assert result.status.calibration_timestamp is not None
    finally:
        manager.stop()


def test_calibrate_gas_sensor_persists_across_new_instance(tmp_path):
    calibration_path = tmp_path / "gas_calibration.json"
    manager, gas_driver, _pir_driver, _alarm_driver, _dht_driver = _make_manager(
        calibration_file_path=calibration_path
    )
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        result = manager.calibrate_gas_sensor()
        assert result.success is True
    finally:
        manager.stop()

    # Simulate an application restart: build a fresh manager pointed at the same file.
    manager2, _gas_driver2, _pir_driver2, _alarm_driver2, _dht_driver2 = _make_manager(
        calibration_file_path=calibration_path
    )
    try:
        status = manager2.get_gas_calibration_status()
        assert status.is_calibrated is True
        assert status.baseline_voltage == result.status.baseline_voltage
    finally:
        manager2.stop()


def test_calibrate_gas_sensor_replaces_previous_baseline(tmp_path):
    manager, gas_driver, _pir_driver, _alarm_driver, _dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        gas_driver.simulate_gas_event(0.5)
        assert _wait_until(lambda: manager.get_gas_status().gas_voltage == pytest.approx(0.5, abs=0.1))
        first = manager.calibrate_gas_sensor()
        assert first.success is True

        gas_driver.simulate_gas_event(1.2)
        assert _wait_until(lambda: manager.get_gas_status().gas_voltage == pytest.approx(1.2, abs=0.1))
        second = manager.calibrate_gas_sensor()
        assert second.success is True
        assert second.status.baseline_voltage != first.status.baseline_voltage
        assert manager.get_gas_calibration_status().baseline_voltage == second.status.baseline_voltage
    finally:
        manager.stop()


def test_calibrate_refused_when_gas_alarm_active(tmp_path):
    manager, gas_driver, _pir_driver, _alarm_driver, _dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        gas_driver.simulate_gas_event(2.0)
        assert _wait_until(lambda: manager.is_gas_alarm_active() is True)

        result = manager.calibrate_gas_sensor()

        assert result.success is False
        assert result.status.is_calibrated is False, "baseline must not be created from an alarm condition"
    finally:
        manager.stop()


def test_calibrate_refused_when_sensor_faulted(tmp_path):
    manager, _gas_driver, _pir_driver, _alarm_driver, dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        dht_driver.force_failure(True)
        assert _wait_until(lambda: manager.get_temperature_c() is None, timeout=1.0)

        result = manager.calibrate_gas_sensor()

        assert result.success is False
        assert result.status.is_calibrated is False, "a failed sensor read must not overwrite/create a baseline"
    finally:
        manager.stop()


def test_temperature_recalibration_exactly_30_is_not_needed(tmp_path):
    # Uses a deterministic (jitter-free) temperature source so the exact
    # 30.0 boundary can be verified precisely.
    fixed_monitor = _FixedTemperatureHumidityMonitor(temperature_c=22.0)
    manager, _gas_driver, _pir_driver, _alarm_driver, _dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json", temperature_humidity_monitor=fixed_monitor
    )
    manager.start()
    try:
        assert manager.calibrate_gas_sensor().success is True

        fixed_monitor.temperature_c = 52.0  # exactly +30
        assert _wait_until(lambda: manager.get_gas_calibration_status().temperature_difference_c == 30.0)

        status = manager.get_gas_calibration_status()
        assert status.recalibration_needed is False
    finally:
        manager.stop()


def test_temperature_recalibration_above_30_is_needed(tmp_path):
    manager, _gas_driver, _pir_driver, _alarm_driver, dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    dht_driver._baseline_temperature_c = 22.0
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        assert manager.calibrate_gas_sensor().success is True

        dht_driver._baseline_temperature_c = 53.0  # +31
        assert _wait_until(lambda: manager.get_temperature_c() == pytest.approx(53.0, abs=0.6))

        status = manager.get_gas_calibration_status()
        assert status.recalibration_needed is True
        assert "TEMPERATURE" in status.recalibration_reasons
    finally:
        manager.stop()


def test_temperature_recalibration_handles_decrease(tmp_path):
    manager, _gas_driver, _pir_driver, _alarm_driver, dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    dht_driver._baseline_temperature_c = 22.0
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        assert manager.calibrate_gas_sensor().success is True

        dht_driver._baseline_temperature_c = -9.0  # -31 difference
        assert _wait_until(lambda: manager.get_temperature_c() == pytest.approx(-9.0, abs=0.6))

        status = manager.get_gas_calibration_status()
        assert status.recalibration_needed is True
        assert "TEMPERATURE" in status.recalibration_reasons
    finally:
        manager.stop()


def test_humidity_recalibration_exactly_40_is_not_needed(tmp_path):
    # Uses a deterministic (jitter-free) humidity source so the exact 40.0
    # percentage-point boundary can be verified precisely.
    fixed_monitor = _FixedTemperatureHumidityMonitor(humidity_percent=40.0)
    manager, _gas_driver, _pir_driver, _alarm_driver, _dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json", temperature_humidity_monitor=fixed_monitor
    )
    manager.start()
    try:
        assert manager.calibrate_gas_sensor().success is True

        fixed_monitor.humidity_percent = 80.0  # exactly +40 points
        assert _wait_until(lambda: manager.get_gas_calibration_status().humidity_difference_rh == 40.0)

        status = manager.get_gas_calibration_status()
        assert status.recalibration_needed is False
    finally:
        manager.stop()


def test_humidity_recalibration_above_40_is_needed(tmp_path):
    manager, _gas_driver, _pir_driver, _alarm_driver, dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    dht_driver._baseline_humidity_percent = 40.0
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_humidity_percent() is not None)
        assert manager.calibrate_gas_sensor().success is True

        dht_driver._baseline_humidity_percent = 85.0  # +45 points
        assert _wait_until(lambda: manager.get_humidity_percent() == pytest.approx(85.0, abs=2.5))

        status = manager.get_gas_calibration_status()
        assert status.recalibration_needed is True
        assert "HUMIDITY" in status.recalibration_reasons
    finally:
        manager.stop()


def test_recalibration_clears_when_back_in_range(tmp_path):
    manager, _gas_driver, _pir_driver, _alarm_driver, dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    dht_driver._baseline_temperature_c = 22.0
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        assert manager.calibrate_gas_sensor().success is True

        dht_driver._baseline_temperature_c = 60.0
        assert _wait_until(lambda: manager.get_gas_calibration_status().recalibration_needed is True)

        dht_driver._baseline_temperature_c = 23.0
        assert _wait_until(lambda: manager.get_gas_calibration_status().recalibration_needed is False)
        # The original baseline itself must be unchanged - only the recommendation cleared.
        assert manager.get_gas_calibration_status().temperature_baseline_c == pytest.approx(22.0, abs=0.6)
    finally:
        manager.stop()


def test_recalibration_does_not_suppress_gas_alarm(tmp_path):
    manager, gas_driver, _pir_driver, alarm_driver, dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    dht_driver._baseline_temperature_c = 22.0
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        assert manager.calibrate_gas_sensor().success is True

        dht_driver._baseline_temperature_c = 60.0  # triggers recalibration recommendation
        gas_driver.simulate_gas_event(2.5)  # also triggers a real gas alarm

        assert _wait_until(
            lambda: manager.is_gas_alarm_active() is True
            and manager.get_gas_calibration_status().recalibration_needed is True
        )
        status = manager.get_gas_calibration_status()
        assert status.gas_alarm_active is True
        assert status.recalibration_needed is True
        assert alarm_driver.buzzer_on is True, "gas alarm must not be suppressed by the recalibration flag"
        assert alarm_driver.led_on is True
    finally:
        manager.stop()


def test_uncalibrated_system_does_not_claim_normal_calibrated_monitoring(tmp_path):
    manager, _gas_driver, _pir_driver, _alarm_driver, _dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    manager.start()
    try:
        assert _wait_until(lambda: manager.get_temperature_c() is not None)
        status = manager.get_gas_calibration_status()
        assert status.is_calibrated is False
        assert status.recalibration_needed is False
        assert status.baseline_voltage is None
    finally:
        manager.stop()


def test_monitoring_continues_regardless_of_power_manager_state(tmp_path):
    # EnvironmentManager has no coupling to any display/power state - its own
    # thread runs independently. No PowerManager is even wired in here.
    manager, gas_driver, _pir_driver, _alarm_driver, _dht_driver = _make_manager(
        calibration_file_path=tmp_path / "gas_calibration.json"
    )
    manager.start()
    try:
        first_timestamp = manager.get_status().timestamp
        assert _wait_until(lambda: manager.get_status().timestamp != first_timestamp)
    finally:
        manager.stop()

