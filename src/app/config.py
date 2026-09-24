"""Central configuration for the environment, safety, and power subsystem."""

from __future__ import annotations

import logging
import os


def _env_bool(name: str, default: bool) -> bool:
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}
# Set KSA_HARDWARE_MODE=1 on the Raspberry Pi to use real hardware drivers.
HARDWARE_MODE: bool = _env_bool("KSA_HARDWARE_MODE", False)

# GPIO pin assignments use BCM numbering. Raspberry Pi 4 Model B physical pins:
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

ADS1115_I2C_ADDRESS: int = 0x48
ADS1115_GAS_CHANNEL: int = 0
ADS1115_GAIN: float = 1.0

# Voltage thresholds are placeholders until MQ-4 bench calibration is complete.
GAS_ALARM_VOLTAGE_THRESHOLD: float = 1.5
GAS_ALARM_HYSTERESIS_VOLTAGE: float = 0.15
GAS_ALARM_DEBOUNCE_SECONDS: float = 3.0
GAS_POLL_INTERVAL_SECONDS: float = 1.0
GAS_SAMPLE_FILTER_WINDOW: int = 5
GAS_MAX_CONSECUTIVE_FAILURES: int = 5

DHT11_POLL_INTERVAL_SECONDS: float = 5.0
DHT11_MAX_CONSECUTIVE_FAILURES: int = 5

PIR_POLL_INTERVAL_SECONDS: float = 0.25
PIR_DEBOUNCE_SECONDS: float = 2.0
PIR_MAX_CONSECUTIVE_FAILURES: int = 5

ENVIRONMENT_MANAGER_POLL_INTERVAL_SECONDS: float = 0.5

UI_INACTIVITY_TIMEOUT_SECONDS: float = 60.0
POWER_MANAGER_POLL_INTERVAL_SECONDS: float = 1.0

LOG_LEVEL: int = logging.INFO
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
