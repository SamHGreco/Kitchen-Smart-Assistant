"""Integrated Pi 4 launcher. See SETUP_STEP_BY_STEP.md in the project root."""
from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
UI = SRC / 'ui'
for directory in (SRC, UI):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from app import config
from app.shared.events import drain_events
from app.shared.models import ActivityType, UIState
from app.shared.scanner_scale_gate import ScannerScaleGate
from environment.alarm import AlarmController
from environment.environment_manager import EnvironmentManager
from environment.hardware.alarm_outputs import RealAlarmOutputDriver
from power.sleep_manager import PowerManager
from Sensor_Interfaces import TeamSensors
from Input_Validation import load_config
from scale.coordinated_scale import build_scale
from ui.main import run_app

LOG = logging.getLogger(__name__)


class SilentAlarmOutputDriver(RealAlarmOutputDriver):
    def set_buzzer(self, on):
        gpio = self._ensure_initialized()
        gpio.output(self._buzzer_pin, gpio.LOW)


def preload_hardware_libraries():
    # Avoid concurrent first imports of Blinka from sensor threads.
    import board
    import busio
    import adafruit_dht
    import adafruit_ads1x15.ads1115
    import RPi.GPIO


def parse_args():
    parser = argparse.ArgumentParser(description='Kitchen Smart Assistant (Pi 4)')
    parser.add_argument('--config', default=str(UI / 'config.pi.json'))
    parser.add_argument('--mockhardware', action='store_true', help='No physical sensors; serial still requires --serial')
    parser.add_argument('--no-environment', action='store_true', help='BENCH ONLY: no environmental sensing or alarms')
    parser.add_argument('--silent', action='store_true', help='DEVELOPMENT ONLY: mute external alarm buzzer')
    parser.add_argument('--serial', action='store_true')
    parser.add_argument('--size', default='800x480')
    parser.add_argument('--fullscreen', action='store_true')
    return parser.parse_args()


def require_review(settings, keys):
    review = settings.get('hardware_review', {})
    missing = [key for key in keys if review.get(key) is not True]
    if missing:
        raise ValueError('Check hardware first; then acknowledge in config.pi.json: ' + ', '.join(missing))


def main():
    args = parse_args()
    if args.mockhardware:
        config.HARDWARE_MODE = False
    logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
    settings = load_config(args.config)
    if config.HARDWARE_MODE:
        require_review(settings, ('scale_wiring_and_capacity_confirmed',
                                 'power_budget_and_connector_orientation_confirmed'))
        if not args.no_environment:
            require_review(settings, ('sensor_wiring_confirmed', 'alarm_outputs_confirmed',
                                     'gas_warmup_complete', 'gas_voltage_thresholds_reviewed'))
            # Keep the active environment pin map aligned with the same JSON file.
            pins = settings['gpio']
            config.DHT11_GPIO_PIN = pins['dht11']
            config.PIR_GPIO_PIN = pins['motion']
            config.BUZZER_GPIO_PIN = pins['buzzer']
            config.ALARM_LED_GPIO_PIN = pins['alarm_led']
            gas = settings['gas']
            config.ADS1115_I2C_ADDRESS = int(gas['ads_address'])
            config.ADS1115_GAS_CHANNEL = int(gas['ads_channel'])
            thresholds = gas['startup_thresholds']
            config.GAS_ALARM_VOLTAGE_THRESHOLD = float(thresholds['threshold_voltage'])
            config.GAS_ALARM_HYSTERESIS_VOLTAGE = float(thresholds['hysteresis_voltage'])
            config.GAS_ALARM_DEBOUNCE_SECONDS = float(thresholds['debounce_seconds'])
            preload_hardware_libraries()
    if args.serial:
        require_review(settings, ('gpio15_conflict_resolved',
                                 'uart_voltage_compatibility_confirmed',
                                 'power_budget_and_connector_orientation_confirmed'))
    elif config.HARDWARE_MODE:
        LOG.warning('No --serial: disconnect scanner power for scale-only bench tests; software does not control it.')

    options = settings.get('scanner_scale', {})
    gate = ScannerScaleGate(
        serial_enabled=args.serial,
        auto_pause=bool(options.get('auto_pause_on_weight', True)) and config.HARDWARE_MODE,
        pause_above_g=float(options.get('pause_above_g', 20.0)),
        resume_below_g=float(options.get('resume_below_g', 5.0)),
        empty_seconds=float(options.get('empty_seconds', 1.0)),
        stop_timeout=float(options.get('stop_timeout', 3.0)),
        settle_seconds=float(options.get('settle_seconds', 0.2)),
    )
    power = PowerManager()
    environment = None
    scale = None
    try:
        power.start()
        if not args.no_environment:
            alarm = None
            if config.HARDWARE_MODE and args.silent:
                alarm = AlarmController(driver=SilentAlarmOutputDriver(
                    config.BUZZER_GPIO_PIN, config.ALARM_LED_GPIO_PIN))
            # Do not pass the scanner/scale busy flag to safety monitors.
            # Gas, temperature and motion continue polling while weighing.
            environment = EnvironmentManager(power_manager=power, alarm_controller=alarm)
            environment.start()
        else:
            LOG.warning('BENCH MODE: environmental sensing and alarms are disabled.')
        if config.HARDWARE_MODE:
            scale = build_scale(settings, gate)
        sensors = TeamSensors(environment=environment, power=power,
                              activity_type=ActivityType, ui_state=UIState,
                              weight_snapshot=scale.snapshot if scale else None,
                              weight_deferred=getattr(scale,'background_read_deferred',None) if scale else None)
        if scale:
            scale.notify_weight = sensors.notify_weight
            scale.start()
        run_app(settings, serial_enabled=args.serial, sensors=sensors,
                read_scale=scale.read if scale else None,
                tare_scale=scale.tare if scale else None,
                scale_controller=scale, scanner_gate=gate,
                gas_calibration=environment, size=args.size,
                fullscreen=args.fullscreen, drain_events=drain_events)
    finally:
        try:
            if scale:
                scale.stop()
        finally:
            try:
                if environment:
                    environment.stop()
            finally:
                power.stop()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        raise SystemExit('Kitchen Assistant stopped: ' + str(exc))
