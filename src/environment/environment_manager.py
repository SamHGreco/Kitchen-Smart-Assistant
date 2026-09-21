"""EnvironmentManager: coordinates all environment/safety sensors (Phase 6).

Aggregates TemperatureHumidityMonitor, GasMonitor, and MotionMonitor into a
single `EnvironmentStatus`, drives the AlarmController from the gas alarm
state, forwards activity/safety-alarm notifications to an (optional)
PowerManager, and publishes state-transition events to the shared event
queue. This is the only module other subsystems should use for
environmental/safety data - never the individual sensor monitors directly.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from app import config
from app.shared.events import EventType, publish_event
from app.shared.models import EnvironmentStatus, SafetyState, SensorHealth, ActivityType
from environment.alarm import AlarmController
from environment.gas_sensor import GasMonitor, GasReading
from environment.motion import MotionMonitor
from environment.temperature_humidity import TemperatureHumidityMonitor

logger = logging.getLogger(__name__)


class EnvironmentManager:
    """Coordinates sensor monitors + the alarm controller and publishes a
    unified `EnvironmentStatus`.

    Public API (safe for other subsystems/threads to call):
        start(), stop(), get_status(), get_temperature_c(),
        get_humidity_percent(), get_gas_status(), is_gas_alarm_active(),
        is_motion_detected()
    """

    def __init__(
        self,
        temperature_humidity_monitor: TemperatureHumidityMonitor | None = None,
        gas_monitor: GasMonitor | None = None,
        motion_monitor: MotionMonitor | None = None,
        alarm_controller: AlarmController | None = None,
        power_manager: object | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        self._temperature_humidity_monitor = temperature_humidity_monitor or TemperatureHumidityMonitor()
        self._gas_monitor = gas_monitor or GasMonitor()
        self._motion_monitor = motion_monitor or MotionMonitor()
        self._alarm_controller = alarm_controller or AlarmController()
        # Typed as `object` to avoid a hard dependency on PowerManager's
        # module; any object with notify_activity()/set_safety_alarm_active()
        # works. Passing None means power notifications are simply skipped.
        self._power_manager = power_manager
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else config.ENVIRONMENT_MANAGER_POLL_INTERVAL_SECONDS
        )

        self._lock = threading.Lock()
        self._status = self._build_status(
            self._temperature_humidity_monitor.get_reading(),
            self._gas_monitor.get_reading(),
            self._motion_monitor.get_reading(),
        )
        self._prev_motion_detected = False
        self._prev_gas_alarm = False
        self._prev_sensor_fault = False

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start all sensor monitors and the aggregation thread. No-op if already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._temperature_humidity_monitor.start()
        self._gas_monitor.start()
        self._motion_monitor.start()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="EnvironmentManager", daemon=True)
        self._thread.start()
        logger.info("Environment manager started")

    def stop(self) -> None:
        """Stop the aggregation thread, all sensor monitors, and de-energize alarms."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval_seconds + 1.0)
            self._thread = None
        self._temperature_humidity_monitor.stop()
        self._gas_monitor.stop()
        self._motion_monitor.stop()
        self._alarm_controller.close()
        logger.info("Environment manager stopped")

    def get_status(self) -> EnvironmentStatus:
        """Return the latest aggregated environment/safety snapshot. Thread-safe."""
        with self._lock:
            return self._status

    def get_temperature_c(self) -> float | None:
        return self.get_status().temperature_c

    def get_humidity_percent(self) -> float | None:
        return self.get_status().humidity_percent

    def get_gas_status(self) -> GasReading:
        """Return the latest raw gas-sensor reading (raw ADC + voltage + alarm flag)."""
        return self._gas_monitor.get_reading()

    def is_gas_alarm_active(self) -> bool:
        return self.get_status().gas_alarm

    def is_motion_detected(self) -> bool:
        return self.get_status().motion_detected

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._aggregate_once()
            self._stop_event.wait(self._poll_interval_seconds)

    def _aggregate_once(self) -> None:
        temp_reading = self._temperature_humidity_monitor.get_reading()
        gas_reading = self._gas_monitor.get_reading()
        motion_reading = self._motion_monitor.get_reading()

        with self._lock:
            self._status = self._build_status(temp_reading, gas_reading, motion_reading)
            status = self._status

        self._alarm_controller.set_alarm_active(status.gas_alarm)
        self._notify_power_manager(status)
        self._publish_transition_events(status)

    def _build_status(self, temp_reading, gas_reading, motion_reading) -> EnvironmentStatus:
        sensor_fault = SensorHealth.FAULT in (
            temp_reading.health,
            gas_reading.health,
            motion_reading.health,
        )
        if gas_reading.gas_alarm:
            safety_state = SafetyState.ALARM
        elif sensor_fault:
            safety_state = SafetyState.SENSOR_FAULT
        elif SensorHealth.DEGRADED in (temp_reading.health, gas_reading.health, motion_reading.health):
            safety_state = SafetyState.WARNING
        else:
            safety_state = SafetyState.NORMAL

        return EnvironmentStatus(
            temperature_c=temp_reading.temperature_c,
            humidity_percent=temp_reading.humidity_percent,
            gas_raw=gas_reading.gas_raw,
            gas_voltage=gas_reading.gas_voltage,
            gas_alarm=gas_reading.gas_alarm,
            motion_detected=motion_reading.motion_detected,
            safety_state=safety_state,
            sensor_fault=sensor_fault,
            temp_humidity_health=temp_reading.health,
            gas_health=gas_reading.health,
            motion_health=motion_reading.health,
            timestamp=datetime.now(timezone.utc),
        )

    def _notify_power_manager(self, status: EnvironmentStatus) -> None:
        if self._power_manager is None:
            return
        if status.motion_detected and not self._prev_motion_detected:
            self._power_manager.notify_activity(ActivityType.MOTION)
        if status.gas_alarm != self._prev_gas_alarm:
            self._power_manager.set_safety_alarm_active(status.gas_alarm)

    def _publish_transition_events(self, status: EnvironmentStatus) -> None:
        if status.motion_detected and not self._prev_motion_detected:
            publish_event(EventType.MOTION_DETECTED)

        if status.gas_alarm and not self._prev_gas_alarm:
            publish_event(EventType.GAS_ALARM_STARTED, {"gas_voltage": status.gas_voltage})
        elif not status.gas_alarm and self._prev_gas_alarm:
            publish_event(EventType.GAS_ALARM_CLEARED, {"gas_voltage": status.gas_voltage})

        if status.sensor_fault and not self._prev_sensor_fault:
            publish_event(
                EventType.ENVIRONMENT_SENSOR_FAULT,
                {
                    "temp_humidity_health": status.temp_humidity_health.value,
                    "gas_health": status.gas_health.value,
                    "motion_health": status.motion_health.value,
                },
            )
        elif not status.sensor_fault and self._prev_sensor_fault:
            publish_event(EventType.ENVIRONMENT_SENSOR_RECOVERED)

        self._prev_motion_detected = status.motion_detected
        self._prev_gas_alarm = status.gas_alarm
        self._prev_sensor_fault = status.sensor_fault
