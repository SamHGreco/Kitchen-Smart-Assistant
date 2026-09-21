import time

from app.shared.models import SensorHealth
from environment.hardware.dht11_driver import MockDHT11Driver
from environment.temperature_humidity import TemperatureHumidityMonitor


def _wait_until(predicate, timeout=2.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_reports_ok_reading_from_mock_driver():
    driver = MockDHT11Driver(baseline_temperature_c=20.0, baseline_humidity_percent=50.0)
    monitor = TemperatureHumidityMonitor(driver=driver, poll_interval_seconds=0.02)
    monitor.start()
    try:
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.OK)
        reading = monitor.get_reading()
        assert reading.temperature_c is not None
        assert reading.humidity_percent is not None
    finally:
        monitor.stop()


def test_degrades_then_faults_then_recovers_without_fabricating_data():
    driver = MockDHT11Driver()
    monitor = TemperatureHumidityMonitor(
        driver=driver, poll_interval_seconds=0.02, max_consecutive_failures=3
    )
    monitor.start()
    try:
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.OK)

        driver.force_failure(True)
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.FAULT)
        reading = monitor.get_reading()
        assert reading.temperature_c is None
        assert reading.humidity_percent is None

        driver.force_failure(False)
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.OK)
        reading = monitor.get_reading()
        assert reading.temperature_c is not None
    finally:
        monitor.stop()
