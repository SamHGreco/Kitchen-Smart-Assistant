
#Stand in for now, needs further testing with hardware and code. Connects existing sensor managers
# NOTE will need to relook at how the gas triggering will be handled with the baseline


from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from types import SimpleNamespace
import math
from threading import RLock
import time


@dataclass(frozen=True)
class SensorSnapshot:
    temperature_c: float | None = None
    humidity_percent: float | None = None
    gas_voltage: float | None = None
    motion_detected: bool | None = None
    connected: bool = False
    safety_state: str | None = None
    alert_message: str | None = None
    alert_id: str | None = None
    note: str = 'Sensors not connected'
    weight_detected: bool | None = None
    weight_g: float | None = None
    gas_alarm: bool | None = None
    sensor_fault: bool = False
    fresh: bool = True
    gas_raw: int | None = None
    temp_alarm: bool | None = None
    humidity_alarm: bool | None = None
    temp_humidity_health: str | None = None
    gas_health: str | None = None
    motion_health: str | None = None
    display_awake: bool | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class GasSettings:
    threshold_voltage: float
    hysteresis_voltage: float
    debounce_seconds: float

    @classmethod
    def read(cls, value):
        def field(name):
            item = value[name] if isinstance(value, dict) else getattr(value, name)
            if isinstance(item, bool):
                raise ValueError(name + ' must be a number.')
            number = float(item)
            if not math.isfinite(number):
                raise ValueError(name + ' must be finite.')
            return number
        result = cls(*(field(name) for name in cls.__dataclass_fields__))
        if result.threshold_voltage <= 0:
            raise ValueError('Threshold must be above zero.')
        if not 0 <= result.hysteresis_voltage < result.threshold_voltage:
            raise ValueError('Hysteresis must be nonnegative and below the threshold.')
        if result.debounce_seconds < 0:
            raise ValueError('Debounce must be nonnegative.')
        return result


class PlaceholderSensors:
    gas_settings_available = False
    reset_available = False

    def snapshot(self):
        return SensorSnapshot()

    def notify_touch(self):
        pass

    def notify_barcode(self):
        pass

    def set_transaction_active(self, active):
        pass

    def set_ui_home(self, home):
        pass

    def get_gas_settings(self):
        raise RuntimeError('No gas controller connected. settings are not applied.')

    def apply_gas_settings(self, settings):
        raise RuntimeError('No gas controller connected. settings are not applied.')

    def reset_alarm(self):
        raise RuntimeError('The alarm reset interface not connected.')


class TeamSensors(PlaceholderSensors):
    def __init__(self, environment, power, activity_type, ui_state, *,
                 weight_snapshot=None, reset_alarm=None, max_age_seconds=5):
        self.environment, self.power = environment, power
        self.activity_type, self.ui_state = activity_type, ui_state
        self.weight_snapshot = weight_snapshot
        self.reset_callback = reset_alarm
        self.max_age_seconds = float(max_age_seconds)
        if not math.isfinite(self.max_age_seconds) or self.max_age_seconds <= 0:
            raise ValueError('max_age_seconds must be positive.')
        self.gas_settings_available = all(callable(getattr(environment, name, None)) for name in
            ('get_gas_alarm_thresholds', 'set_gas_alarm_thresholds'))
        self.reset_available = callable(reset_alarm)

    def _fresh(self, stamp):
        if not isinstance(stamp, datetime) or stamp.tzinfo is None:
            return False
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        return -1 <= age <= self.max_age_seconds

    def snapshot(self):
        #Reads cached values only
        s = (self.environment.get_status() if self.environment is not None else
             SimpleNamespace(timestamp=datetime.now(timezone.utc)))
        safety = getattr(s, 'safety_state', None)
        safety = getattr(safety, 'name', safety)
        alarm = getattr(s, 'gas_alarm', None)
        fresh = self._fresh(getattr(s, 'timestamp', None))
        motion = getattr(s, 'motion_detected', None)
        weight, grams = None, None
        fault = bool(getattr(s, 'sensor_fault', False)) or safety == 'SENSOR_FAULT'
        scale_note = ''
        if self.weight_snapshot:
            try:
                w = self.weight_snapshot()
                wfresh = self._fresh(w.get('timestamp'))
                fault = fault or bool(w.get('fault')) or not wfresh
                weight = w.get('detected') if wfresh else None
                grams = w.get('grams') if wfresh else None
                if w.get('fault') or not wfresh:
                    scale_note = ' / ' + str(w.get('note') or 'Scale unavailable')
            except Exception:
                fault = True
                scale_note = ' / Scale interface error'
        active = (safety == 'ALARM' or alarm is True or
                  getattr(s, 'temp_alarm', None) is True or getattr(s, 'humidity_alarm', None) is True)
        if active:
            safety = 'ALARM'
        return SensorSnapshot(
            temperature_c=getattr(s, 'temperature_c', None) if fresh else None,
            humidity_percent=getattr(s, 'humidity_percent', None) if fresh else None,
            gas_voltage=getattr(s, 'gas_voltage', None) if fresh else None,
            motion_detected=motion,
            connected=self.environment is not None, safety_state=safety,
            alert_id='environment-ALARM' if active else None,
            alert_message='Environmental alarm reported by controller.' if active else None,
            note=getattr(self, 'mode_note', '') + (str(safety or ('Status unavailable' if self.environment is not None else 'Environment not connected')) if fresh else 'Stale or missing sensor timestamp') + scale_note,
            weight_detected=weight, weight_g=grams,
            gas_alarm=alarm if isinstance(alarm, bool) else None,
            sensor_fault=fault, fresh=fresh,
            gas_raw=getattr(s, 'gas_raw', None) if fresh else None,
            temp_alarm=getattr(s, 'temp_alarm', None),
            humidity_alarm=getattr(s, 'humidity_alarm', None),
            temp_humidity_health=self._health(s, 'temp_humidity_health'),
            gas_health=self._health(s, 'gas_health'),
            motion_health=self._health(s, 'motion_health'),
            display_awake=self.power.is_display_awake() if self.power and callable(getattr(self.power, 'is_display_awake', None)) else None,
            timestamp=getattr(s, 'timestamp', None),
        )

    @staticmethod
    def _health(status, name):
        value = getattr(status, name, None)
        return getattr(value, 'name', value)

    def notify_weight(self):
        if self.power:
            self.power.notify_activity(self.activity_type.WEIGHT)

    def get_gas_settings(self):
        #Reads the controller settings
        return GasSettings.read(self.environment.get_gas_alarm_thresholds())

    def apply_gas_settings(self, settings):
        settings = GasSettings.read(settings)
        self.environment.set_gas_alarm_thresholds(**asdict(settings))
        try:
            return self.get_gas_settings()
        except Exception as exc:
            raise RuntimeError('Setting sent but readback failed. Verify controller settings: ' + str(exc)) from exc

    def reset_alarm(self):
        if not self.reset_available:
            return super().reset_alarm()
        #Controller decides whether reset is allowed
        return self.reset_callback()

    def notify_touch(self):
        if self.power:
            self.power.notify_activity(self.activity_type.TOUCH)

    def notify_barcode(self):
        if self.power:
            self.power.notify_activity(self.activity_type.BARCODE)

    def set_transaction_active(self, active):
        if self.power:
            self.power.set_transaction_active(active)

    def set_ui_home(self, home):
        if self.power:
            setter = getattr(self.power, 'set_ui_state', None) or getattr(self.power, 'ui_state', None)
            if not callable(setter):
                raise RuntimeError('Power manager needs set_ui_state().')
            setter(self.ui_state.HOME if home else self.ui_state.OTHER)


class DemoSensors(PlaceholderSensors):
    #To complete testing without hardware
    gas_settings_available = True
    reset_available = True

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = RLock()
        self.settings = GasSettings(1.0, 0.1, 0.5)
        self.motion = False
        self.weight = False
        self.high_gas = False
        self.fault = False
        self.alarm = False
        self.high_since = None

    def set_input(self, name, value):
        if name not in ('motion', 'weight', 'high_gas', 'fault') or type(value) is not bool:
            raise ValueError('Use a supported demo input and True or False.')
        with self.lock:
            setattr(self, name, value)
            if name == 'high_gas' and not value:
                self.high_since = None

    def snapshot(self):
        with self.lock:
            now = self.clock()
            v = self.settings.threshold_voltage + 0.2 if self.high_gas else 0.0
            if not self.fault and v >= self.settings.threshold_voltage:
                if self.high_since is None:
                    self.high_since = now
                if now - self.high_since >= self.settings.debounce_seconds:
                    self.alarm = True
            elif not self.fault:
                self.high_since = None
            return SensorSnapshot(
                temperature_c=None, humidity_percent=None,
                gas_voltage=None if self.fault else v,
                motion_detected=self.motion, weight_detected=self.weight,
                weight_g=500.0 if self.weight else 0.0,
                connected=True, gas_alarm=self.alarm,
                safety_state='ALARM' if self.alarm else 'SENSOR_FAULT' if self.fault else 'NORMAL',
                sensor_fault=self.fault, fresh=not self.fault,
                note='DEMO only - no live sensors',
            )

    def get_gas_settings(self):
        with self.lock:
            return self.settings

    def apply_gas_settings(self, settings):
        with self.lock:
            self.settings = GasSettings.read(settings)
            self.high_since = None
            return self.settings

    def reset_alarm(self):
        with self.lock:
            if self.high_gas or self.fault:
                raise RuntimeError('Cannot reset: demo input is high or unavailable.')
            self.alarm = False
            self.high_since = None
            return True
