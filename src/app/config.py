"""Central configuration for the environment / safety / power subsystem.

All GPIO pin numbers, I2C addresses, ADC channel assignments, alarm
thresholds, and timing constants live here so they can be tuned without
touching subsystem logic. Values marked "TODO: CONFIRM" depend on the final
wiring harness and must be set before HARDWARE_MODE is enabled.
"""

from __future__ import annotations

import logging
import os


def _env_bool(name: str, default: bool) -> bool:
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}

# ---------------------------------------------------------------------------
# Hardware / mock mode
# ---------------------------------------------------------------------------
# When False, every driver in this subsystem uses a simulated (mock)
# implementation so the app can run on a dev machine without a Raspberry Pi.
HARDWARE_MODE: bool = _env_bool("KSA_HARDWARE_MODE", False)

# ---------------------------------------------------------------------------
# GPIO pin assignments (BCM numbering)
# ---------------------------------------------------------------------------
# Raspberry Pi 4 Model B physical pin mapping:
# DHT11: GPIO26 / physical pin 37
# HC-SR501 PIR: GPIO17 / physical pin 11
# Active buzzer NPN driver: GPIO22 / physical pin 15
# Alarm LED: GPIO27 / physical pin 13
# ADS1115 ALERT/RDY: GPIO4 / physical pin 7
DHT11_GPIO_PIN: int | None = 26
PIR_GPIO_PIN: int | None = 17
BUZZER_GPIO_PIN: int | None = 22
ALARM_LED_GPIO_PIN: int | None = 27
ADS1115_ALERT_READY_GPIO_PIN: int | None = 4

# ---------------------------------------------------------------------------
# ADS1115 / MQ-4 gas sensor
# ---------------------------------------------------------------------------
ADS1115_I2C_ADDRESS: int = 0x48  # ADS1115 default address (ADDR pin -> GND)
ADS1115_GAS_CHANNEL: int = 0  # MQ-4 analog output connected to ADS1115 A0
ADS1115_GAIN: float = 1.0  # +-4.096V full-scale range

# These are RAW/VOLTAGE placeholders, not calibrated ppm values. Do not treat
# the MQ-4 as ppm-accurate until bench calibration has been performed.
GAS_ALARM_VOLTAGE_THRESHOLD: float = 1.5  # volts, TODO: CONFIRM via calibration
GAS_ALARM_HYSTERESIS_VOLTAGE: float = 0.15  # volts below threshold required to clear the alarm
GAS_ALARM_DEBOUNCE_SECONDS: float = 3.0  # sustained condition required before declaring ALARM
GAS_POLL_INTERVAL_SECONDS: float = 1.0
GAS_SAMPLE_FILTER_WINDOW: int = 5  # moving-average window size used to filter noisy readings
GAS_MAX_CONSECUTIVE_FAILURES: int = 5  # failures before sensor health becomes FAULT

# ---------------------------------------------------------------------------
# DHT11 temperature / humidity
# ---------------------------------------------------------------------------
DHT11_POLL_INTERVAL_SECONDS: float = 5.0
DHT11_MAX_CONSECUTIVE_FAILURES: int = 5  # failures before sensor health becomes FAULT

# ---------------------------------------------------------------------------
# PIR motion
# ---------------------------------------------------------------------------
PIR_POLL_INTERVAL_SECONDS: float = 0.25
PIR_DEBOUNCE_SECONDS: float = 2.0  # minimum time motion must persist/clear to change state
PIR_MAX_CONSECUTIVE_FAILURES: int = 5  # failures before sensor health becomes FAULT

# ---------------------------------------------------------------------------
# EnvironmentManager
# ---------------------------------------------------------------------------
ENVIRONMENT_MANAGER_POLL_INTERVAL_SECONDS: float = 0.5  # how often to aggregate sensor status

# ---------------------------------------------------------------------------
# UI power management
# ---------------------------------------------------------------------------
UI_INACTIVITY_TIMEOUT_SECONDS: float = 60.0
POWER_MANAGER_POLL_INTERVAL_SECONDS: float = 1.0  # how often to check the inactivity timeout

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: int = logging.INFO
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
