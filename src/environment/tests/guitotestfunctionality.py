"""Manual test harness GUI for the Environmental / Safety / Power subsystem.

Run directly:

    python src/environment/tests/guitotestfunctionality.py

This launches a tkinter GUI that lets you manually simulate hardware inputs
(temperature, humidity, gas voltage, motion, sensor failures) and watch the
REAL production logic (TemperatureHumidityMonitor, GasMonitor, MotionMonitor,
EnvironmentManager, AlarmController, PowerManager) react to them. It never
duplicates production decision-making (thresholds, debounce, hysteresis,
sleep/wake rules) - it only feeds simulated sensor values into the same
mock drivers/classes used by the real subsystem, then reads back the real
outputs.

No production files are modified for this harness. The one testability gap
found (MockDHT11Driver has no way to change its simulated reading after
construction, unlike the gas/motion mocks) is worked around with a small
local subclass defined below - it does not change any existing interface or
behavior, it only adds a new method.

Runs fully on a normal dev machine: only Mock* drivers are ever constructed
here, and the Real* drivers already defer all hardware-specific imports
(RPi.GPIO / board / adafruit_dht) to first use, so nothing hardware-specific
is ever imported by this file.
"""

from __future__ import annotations

import sys
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import ttk

# ============================================================
# BOOTSTRAP - make the production `src` packages importable
# ============================================================
# This file lives at src/environment/tests/, so `parents[2]` is `src` itself.
_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from app.shared.events import drain_events  # noqa: E402
from app.shared.models import ActivityType, SafetyState, SensorHealth, UIState  # noqa: E402
from environment.alarm import AlarmController  # noqa: E402
from environment.environment_manager import EnvironmentManager  # noqa: E402
from environment.gas_sensor import GasMonitor  # noqa: E402
from environment.hardware.ads1115_driver import MockADS1115Driver  # noqa: E402
from environment.hardware.alarm_outputs import MockAlarmOutputDriver  # noqa: E402
from environment.hardware.dht11_driver import MockDHT11Driver  # noqa: E402
from environment.hardware.pir_driver import MockPIRDriver  # noqa: E402
from environment.motion import MotionMonitor  # noqa: E402
from environment.temperature_humidity import TemperatureHumidityMonitor  # noqa: E402
from power.sleep_manager import PowerManager  # noqa: E402

# ============================================================
# LOCAL TEST-ONLY HELPER CLASSES
# ============================================================
# Everything in this section exists ONLY for this manual GUI and is not part
# of the production subsystem.


class GuiControllableDHT11Driver(MockDHT11Driver):
    """MockDHT11Driver + a way to change the simulated reading at runtime.

    The production MockDHT11Driver only sets a baseline temperature/humidity
    at construction time (mirroring how a real sensor has no "set" concept).
    For manual testing we need to change it live from slider input, so this
    subclass adds `set_values()`, which just writes to the same attributes
    `read()` already uses. `read()` itself is not overridden - the same
    production jitter/failure logic still runs unchanged.
    """

    def set_values(self, temperature_c: float | None = None, humidity_percent: float | None = None) -> None:
        if temperature_c is not None:
            self._baseline_temperature_c = temperature_c
        if humidity_percent is not None:
            self._baseline_humidity_percent = humidity_percent


# GUI-only tuning: faster polling than the config.py production defaults so
# the display feels responsive to slider changes. Thresholds, hysteresis,
# and debounce timings are NOT overridden here - those stay at the real
# config.py values so the manual test reflects true production timing.
_GUI_TEMP_POLL_SECONDS = 0.3
_GUI_GAS_POLL_SECONDS = 0.2
_GUI_MOTION_POLL_SECONDS = 0.1
_GUI_ENV_MANAGER_POLL_SECONDS = 0.2
_GUI_POWER_POLL_SECONDS = 0.2
# Shortened from config.UI_INACTIVITY_TIMEOUT_SECONDS (60s) purely so the
# "display goes to sleep" behavior can be observed without a long wait.
_GUI_INACTIVITY_TIMEOUT_SECONDS = 10.0

_REFRESH_MS = 200  # GUI output/log refresh rate

_HEALTH_COLORS = {
    SensorHealth.OK: "#1a7f37",
    SensorHealth.DEGRADED: "#b35c00",
    SensorHealth.FAULT: "#b00020",
}
_SAFETY_COLORS = {
    SafetyState.NORMAL: "#1a7f37",
    SafetyState.WARNING: "#b35c00",
    SafetyState.ALARM: "#b00020",
    SafetyState.SENSOR_FAULT: "#7b1fa2",
}
_BOOL_COLORS = {True: "#b00020", False: "#1a7f37"}


class ManualTestApp:
    """Top-level tkinter application wiring the GUI to the real subsystem."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Environment / Safety / Power - Manual Test Harness")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # --- Real production objects, wired together exactly like main.py would ---
        self._dht_driver = GuiControllableDHT11Driver(baseline_temperature_c=22.0, baseline_humidity_percent=45.0)
        self._gas_driver = MockADS1115Driver(baseline_voltage=0.4)
        self._pir_driver = MockPIRDriver()
        self._alarm_driver = MockAlarmOutputDriver()

        self._temp_monitor = TemperatureHumidityMonitor(driver=self._dht_driver, poll_interval_seconds=_GUI_TEMP_POLL_SECONDS)
        self._gas_monitor = GasMonitor(driver=self._gas_driver, poll_interval_seconds=_GUI_GAS_POLL_SECONDS)
        self._motion_monitor = MotionMonitor(driver=self._pir_driver, poll_interval_seconds=_GUI_MOTION_POLL_SECONDS)
        self._alarm_controller = AlarmController(driver=self._alarm_driver)
        self._power_manager = PowerManager(
            inactivity_timeout_seconds=_GUI_INACTIVITY_TIMEOUT_SECONDS,
            poll_interval_seconds=_GUI_POWER_POLL_SECONDS,
        )
        self._environment_manager = EnvironmentManager(
            temperature_humidity_monitor=self._temp_monitor,
            gas_monitor=self._gas_monitor,
            motion_monitor=self._motion_monitor,
            alarm_controller=self._alarm_controller,
            power_manager=self._power_manager,
            poll_interval_seconds=_GUI_ENV_MANAGER_POLL_SECONDS,
        )

        self._build_ui()

        self._power_manager.start()
        self._environment_manager.start()
        self._log("Subsystem started (mock hardware).")

        self._prev_safety_state: SafetyState | None = None
        self._prev_buzzer_on: bool | None = None
        self._prev_led_on: bool | None = None

        self.root.after(_REFRESH_MS, self._refresh)

    # ============================================================
    # UI CONSTRUCTION
    # ============================================================
    def _build_ui(self) -> None:
        left = ttk.Frame(self.root, padding=8)
        left.grid(row=0, column=0, sticky="nsew")
        right = ttk.Frame(self.root, padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        bottom = ttk.Frame(self.root, padding=8)
        bottom.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        self._build_simulated_inputs_section(left)
        self._build_external_inputs_section(left)
        self._build_test_scenarios_section(left)
        self._build_outputs_section(right)
        self._build_integration_interface_section(right)
        self._build_log_section(bottom)

    # ============================================================
    # SIMULATED HARDWARE INPUTS
    # ============================================================
    def _build_simulated_inputs_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="1. Simulated Inputs", padding=8)
        box.pack(fill="x", pady=(0, 8))

        # --- Temperature / Humidity (DHT11) ---
        ttk.Label(box, text="Temperature (C)").grid(row=0, column=0, sticky="w")
        self._temp_var = tk.DoubleVar(value=22.0)
        ttk.Scale(box, from_=-10, to=50, variable=self._temp_var, orient="horizontal").grid(row=0, column=1, sticky="ew")
        ttk.Button(box, text="Set Temperature", command=self._on_set_temperature).grid(row=0, column=2, padx=4)

        ttk.Label(box, text="Humidity (%RH)").grid(row=1, column=0, sticky="w")
        self._humidity_var = tk.DoubleVar(value=45.0)
        ttk.Scale(box, from_=0, to=100, variable=self._humidity_var, orient="horizontal").grid(row=1, column=1, sticky="ew")
        ttk.Button(box, text="Set Humidity", command=self._on_set_humidity).grid(row=1, column=2, padx=4)

        self._temp_fail_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            box, text="Simulate DHT11 sensor failure", variable=self._temp_fail_var, command=self._on_toggle_temp_failure
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 8))

        # --- Gas (MQ-4 via ADS1115) - same unit (voltage) the production code expects ---
        from app import config as _config

        ttk.Label(
            box, text=f"Gas voltage (V) - alarm threshold {_config.GAS_ALARM_VOLTAGE_THRESHOLD:.2f}V"
        ).grid(row=3, column=0, columnspan=3, sticky="w")
        self._gas_var = tk.DoubleVar(value=0.4)
        ttk.Scale(box, from_=0.0, to=3.3, variable=self._gas_var, orient="horizontal").grid(row=4, column=1, sticky="ew")
        ttk.Button(box, text="Set Gas Voltage", command=self._on_set_gas_voltage).grid(row=4, column=2, padx=4)
        gas_buttons = ttk.Frame(box)
        gas_buttons.grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 2))
        ttk.Button(gas_buttons, text="Simulate Gas Normal", command=self._on_gas_normal).pack(side="left")
        ttk.Button(gas_buttons, text="Simulate Gas Alarm", command=self._on_gas_alarm).pack(side="left", padx=4)

        self._gas_fail_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            box, text="Simulate gas sensor (ADS1115) failure", variable=self._gas_fail_var, command=self._on_toggle_gas_failure
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(2, 8))

        # --- Motion (PIR) ---
        motion_buttons = ttk.Frame(box)
        motion_buttons.grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Button(motion_buttons, text="Motion Detected", command=self._on_motion_detected).pack(side="left")
        ttk.Button(motion_buttons, text="No Motion", command=self._on_no_motion).pack(side="left", padx=4)

        self._motion_fail_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            box, text="Simulate PIR sensor failure", variable=self._motion_fail_var, command=self._on_toggle_motion_failure
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=(2, 0))

        box.grid_columnconfigure(1, weight=1)

    # ============================================================
    # INPUTS FROM OTHER SUBSYSTEMS
    # ============================================================
    def _build_external_inputs_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="4. External Subsystem Inputs", padding=8)
        box.pack(fill="x", pady=(0, 8))
        ttk.Label(
            box,
            text="PowerManager needs these from Bobby's UI / Jamie's scale subsystem:",
            wraplength=320,
        ).pack(anchor="w")

        activity_buttons = ttk.Frame(box)
        activity_buttons.pack(fill="x", pady=(4, 4))
        ttk.Button(activity_buttons, text="Simulate Touch (Bobby)", command=self._on_touch).pack(side="left")
        ttk.Button(activity_buttons, text="Simulate Barcode Scan (Bobby)", command=self._on_barcode).pack(side="left", padx=4)
        ttk.Button(activity_buttons, text="Simulate Weight Change (Jamie)", command=self._on_weight).pack(side="left")

        ui_state_frame = ttk.Frame(box)
        ui_state_frame.pack(fill="x", pady=(4, 4))
        ttk.Label(ui_state_frame, text="UI state (Bobby):").pack(side="left")
        self._ui_state_var = tk.StringVar(value=UIState.HOME.value)
        ttk.Radiobutton(
            ui_state_frame, text="HOME", value=UIState.HOME.value, variable=self._ui_state_var, command=self._on_ui_state_change
        ).pack(side="left", padx=4)
        ttk.Radiobutton(
            ui_state_frame, text="OTHER", value=UIState.OTHER.value, variable=self._ui_state_var, command=self._on_ui_state_change
        ).pack(side="left")

        self._transaction_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            box,
            text="Inventory transaction active (Bobby) - blocks display sleep",
            variable=self._transaction_var,
            command=self._on_transaction_toggle,
        ).pack(anchor="w")

        ttk.Separator(box).pack(fill="x", pady=6)
        ttk.Label(
            box,
            text="Bobby's UI can also reach in and change alarm tuning at runtime:",
            wraplength=320,
        ).pack(anchor="w")
        self._threshold_vars: dict[str, tk.StringVar] = {}
        for key, caption, current in (
            ("gas", "Gas alarm threshold (V)", self._environment_manager.get_gas_alarm_thresholds().threshold_voltage),
            ("temp", "High-temp alarm threshold (C)", self._environment_manager.get_temp_alarm_thresholds().threshold_c),
            (
                "humidity",
                "High-humidity alarm threshold (%)",
                self._environment_manager.get_humidity_alarm_thresholds().threshold_percent,
            ),
        ):
            row = ttk.Frame(box)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=caption, width=24, anchor="w").pack(side="left")
            var = tk.StringVar(value=f"{current:.2f}")
            self._threshold_vars[key] = var
            ttk.Entry(row, textvariable=var, width=8).pack(side="left")
            ttk.Button(row, text="Apply", command=lambda k=key: self._on_apply_threshold(k)).pack(side="left", padx=4)

    # ============================================================
    # TEST SCENARIOS
    # ============================================================
    def _build_test_scenarios_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="5. Test Scenarios", padding=8)
        box.pack(fill="x")
        for text, handler in (
            ("Normal Conditions", self._on_scenario_normal),
            ("High Temperature", self._on_scenario_high_temp),
            ("High Humidity", self._on_scenario_high_humidity),
            ("Gas Alarm", self._on_scenario_gas_alarm),
            ("Motion Detected", self._on_scenario_motion),
            ("Sensor Failure", self._on_scenario_sensor_failure),
            ("Reset All", self._on_scenario_reset_all),
        ):
            ttk.Button(box, text=text, command=handler).pack(fill="x", pady=1)

    # ============================================================
    # SUBSYSTEM OUTPUTS
    # ============================================================
    def _build_outputs_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="2. Subsystem Outputs", padding=8)
        box.pack(fill="x", pady=(0, 8))
        self._output_labels: dict[str, tk.Label] = {}
        for key, caption in (
            ("temperature", "Temperature Status"),
            ("humidity", "Humidity Status"),
            ("temp_alarm", "TEMP ALARM"),
            ("humidity_alarm", "HUMIDITY ALARM"),
            ("gas_alarm", "GAS ALARM"),
            ("motion", "MOTION"),
            ("buzzer", "BUZZER"),
            ("led", "LED"),
            ("safety_state", "Overall Safety Status"),
        ):
            row = ttk.Frame(box)
            row.pack(fill="x")
            ttk.Label(row, text=f"{caption}:", width=20, anchor="w").pack(side="left")
            value_label = tk.Label(row, text="-", anchor="w", font=("TkDefaultFont", 10, "bold"))
            value_label.pack(side="left")
            self._output_labels[key] = value_label

    # ============================================================
    # EXTERNAL INTERFACE VARIABLES
    # ============================================================
    def _build_integration_interface_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="3. Integration Interface (from EnvironmentManager.get_status())", padding=8)
        box.pack(fill="x", pady=(0, 8))
        self._interface_labels: dict[str, tk.Label] = {}
        for field in (
            "temperature_c",
            "humidity_percent",
            "temp_alarm",
            "humidity_alarm",
            "gas_raw",
            "gas_voltage",
            "gas_alarm",
            "motion_detected",
            "safety_state",
            "sensor_fault",
            "temp_humidity_health",
            "gas_health",
            "motion_health",
            "timestamp",
        ):
            row = ttk.Frame(box)
            row.pack(fill="x")
            ttk.Label(row, text=f"{field}:", width=22, anchor="w", font=("TkFixedFont", 9)).pack(side="left")
            value_label = tk.Label(row, text="-", anchor="w", font=("TkFixedFont", 9))
            value_label.pack(side="left")
            self._interface_labels[field] = value_label

        ttk.Separator(box).pack(fill="x", pady=4)
        for key, caption in (
            ("power.is_display_awake()", "power.is_display_awake()"),
            ("alarm.is_alarm_active()", "alarm.is_alarm_active()"),
            ("last_event", "Last event (from drain_events())"),
        ):
            row = ttk.Frame(box)
            row.pack(fill="x")
            ttk.Label(row, text=f"{caption}:", width=22, anchor="w", font=("TkFixedFont", 9)).pack(side="left")
            value_label = tk.Label(row, text="-", anchor="w", font=("TkFixedFont", 9))
            value_label.pack(side="left")
            self._interface_labels[key] = value_label

    # ============================================================
    # DIAGNOSTIC LOG
    # ============================================================
    def _build_log_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="6. Event / Diagnostic Log", padding=8)
        box.pack(fill="both", expand=True)
        self._log_text = tk.Text(box, height=10, state="disabled", font=("TkFixedFont", 9))
        scrollbar = ttk.Scrollbar(box, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scrollbar.set)
        self._log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", f"[{timestamp}] {message}\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    # ============================================================
    # GUI EVENT HANDLERS - Simulated Inputs
    # ============================================================
    def _on_set_temperature(self) -> None:
        self._apply_temperature(self._temp_var.get())

    def _on_set_humidity(self) -> None:
        self._apply_humidity(self._humidity_var.get())

    def _on_set_gas_voltage(self) -> None:
        self._apply_gas_voltage(self._gas_var.get())

    def _on_gas_normal(self) -> None:
        self._apply_gas_voltage(0.4)

    def _on_gas_alarm(self) -> None:
        self._apply_gas_voltage(2.0)

    def _on_motion_detected(self) -> None:
        self._pir_driver.trigger_motion(True)
        self._log("GUI: PIR triggered - motion detected")

    def _on_no_motion(self) -> None:
        self._pir_driver.trigger_motion(False)
        self._log("GUI: PIR cleared - no motion")

    def _on_toggle_temp_failure(self) -> None:
        active = self._temp_fail_var.get()
        self._dht_driver.force_failure(active)
        self._log(f"GUI: DHT11 failure simulation {'ON' if active else 'OFF'}")

    def _on_toggle_gas_failure(self) -> None:
        active = self._gas_fail_var.get()
        self._gas_driver.force_failure(active)
        self._log(f"GUI: ADS1115 failure simulation {'ON' if active else 'OFF'}")

    def _on_toggle_motion_failure(self) -> None:
        active = self._motion_fail_var.get()
        self._pir_driver.force_failure(active)
        self._log(f"GUI: PIR failure simulation {'ON' if active else 'OFF'}")

    # ============================================================
    # GUI EVENT HANDLERS - Inputs From Other Subsystems
    # ============================================================
    def _on_touch(self) -> None:
        self._power_manager.notify_activity(ActivityType.TOUCH)
        self._log("GUI: simulated touch activity (from Bobby's UI)")

    def _on_barcode(self) -> None:
        self._power_manager.notify_activity(ActivityType.BARCODE)
        self._log("GUI: simulated barcode scan activity (from Bobby's UI)")

    def _on_weight(self) -> None:
        self._power_manager.notify_activity(ActivityType.WEIGHT)
        self._log("GUI: simulated weight-change activity (from Jamie's scale)")

    def _on_ui_state_change(self) -> None:
        state = UIState(self._ui_state_var.get())
        self._power_manager.set_ui_state(state)
        self._log(f"GUI: set_ui_state({state.name})")

    def _on_transaction_toggle(self) -> None:
        active = self._transaction_var.get()
        self._power_manager.set_transaction_active(active)
        self._log(f"GUI: set_transaction_active({active})")

    def _on_apply_threshold(self, key: str) -> None:
        try:
            value = float(self._threshold_vars[key].get())
        except ValueError:
            self._log(f"GUI: invalid {key} threshold value entered - ignored")
            return
        if key == "gas":
            self._environment_manager.set_gas_alarm_thresholds(threshold_voltage=value)
            self._log(f"GUI: set_gas_alarm_thresholds(threshold_voltage={value:.2f})")
        elif key == "temp":
            self._environment_manager.set_temp_alarm_thresholds(threshold_c=value)
            self._log(f"GUI: set_temp_alarm_thresholds(threshold_c={value:.2f})")
        else:
            self._environment_manager.set_humidity_alarm_thresholds(threshold_percent=value)
            self._log(f"GUI: set_humidity_alarm_thresholds(threshold_percent={value:.2f})")

    # ============================================================
    # GUI EVENT HANDLERS - Test Scenarios
    # ============================================================
    def _on_scenario_normal(self) -> None:
        self._log("SCENARIO: Normal Conditions")
        self._apply_temperature(22.0)
        self._apply_humidity(45.0)
        self._apply_gas_voltage(0.4)
        self._pir_driver.trigger_motion(False)

    def _on_scenario_high_temp(self) -> None:
        self._log("SCENARIO: High Temperature")
        self._apply_temperature(38.0)

    def _on_scenario_high_humidity(self) -> None:
        self._log("SCENARIO: High Humidity")
        self._apply_humidity(92.0)

    def _on_scenario_gas_alarm(self) -> None:
        self._log("SCENARIO: Gas Alarm")
        self._apply_gas_voltage(2.2)

    def _on_scenario_motion(self) -> None:
        self._log("SCENARIO: Motion Detected")
        self._pir_driver.trigger_motion(True)

    def _on_scenario_sensor_failure(self) -> None:
        self._log("SCENARIO: Sensor Failure (all sensors)")
        for var, driver in (
            (self._temp_fail_var, self._dht_driver),
            (self._gas_fail_var, self._gas_driver),
            (self._motion_fail_var, self._pir_driver),
        ):
            var.set(True)
            driver.force_failure(True)

    def _on_scenario_reset_all(self) -> None:
        self._log("SCENARIO: Reset All")
        for var, driver in (
            (self._temp_fail_var, self._dht_driver),
            (self._gas_fail_var, self._gas_driver),
            (self._motion_fail_var, self._pir_driver),
        ):
            var.set(False)
            driver.force_failure(False)
        self._apply_temperature(22.0)
        self._apply_humidity(45.0)
        self._apply_gas_voltage(0.4)
        self._pir_driver.trigger_motion(False)
        self._transaction_var.set(False)
        self._power_manager.set_transaction_active(False)
        self._ui_state_var.set(UIState.HOME.value)
        self._power_manager.set_ui_state(UIState.HOME)

    # --- shared apply helpers (update driver + slider + log in one place) ---
    def _apply_temperature(self, value: float) -> None:
        self._dht_driver.set_values(temperature_c=value)
        self._temp_var.set(value)
        self._log(f"GUI: set simulated temperature to {value:.1f}C")

    def _apply_humidity(self, value: float) -> None:
        self._dht_driver.set_values(humidity_percent=value)
        self._humidity_var.set(value)
        self._log(f"GUI: set simulated humidity to {value:.1f}%RH")

    def _apply_gas_voltage(self, value: float) -> None:
        self._gas_driver.simulate_gas_event(value)
        self._gas_var.set(value)
        self._log(f"GUI: set simulated gas voltage to {value:.2f}V")

    # ============================================================
    # PERIODIC REFRESH - reads real subsystem outputs, never decides anything
    # ============================================================
    def _refresh(self) -> None:
        status = self._environment_manager.get_status()
        display_awake = self._power_manager.is_display_awake()
        alarm_active = self._alarm_controller.is_alarm_active()

        self._update_outputs(status, alarm_active)
        self._update_integration_interface(status, display_awake, alarm_active)
        self._drain_and_log_events()
        self._log_local_transitions(status, alarm_active)

        self.root.after(_REFRESH_MS, self._refresh)

    def _update_outputs(self, status, alarm_active: bool) -> None:
        temp_text = "-" if status.temperature_c is None else f"{status.temperature_c:.1f}C / {status.temperature_f:.1f}F"
        humidity_text = "-" if status.humidity_percent is None else f"{status.humidity_percent:.1f}%RH"
        self._output_labels["temperature"].configure(text=temp_text)
        self._output_labels["humidity"].configure(text=humidity_text)
        self._set_bool_label(self._output_labels["temp_alarm"], status.temp_alarm, "TRUE", "FALSE")
        self._set_bool_label(self._output_labels["humidity_alarm"], status.humidity_alarm, "TRUE", "FALSE")
        self._set_bool_label(self._output_labels["gas_alarm"], status.gas_alarm, "TRUE", "FALSE")
        self._set_bool_label(self._output_labels["motion"], status.motion_detected, "TRUE", "FALSE")
        self._set_bool_label(self._output_labels["buzzer"], self._alarm_driver.buzzer_on, "ON", "OFF")
        self._set_bool_label(self._output_labels["led"], self._alarm_driver.led_on, "ON", "OFF")
        safety_label = self._output_labels["safety_state"]
        safety_label.configure(text=status.safety_state.name, fg=_SAFETY_COLORS[status.safety_state])

    def _set_bool_label(self, label: tk.Label, value: bool, true_text: str, false_text: str) -> None:
        label.configure(text=true_text if value else false_text, fg=_BOOL_COLORS[value])

    def _update_integration_interface(self, status, display_awake: bool, alarm_active: bool) -> None:
        def health_text(label: tk.Label, health: SensorHealth) -> None:
            label.configure(text=health.value, fg=_HEALTH_COLORS[health])

        self._interface_labels["temperature_c"].configure(text=str(status.temperature_c))
        self._interface_labels["humidity_percent"].configure(text=str(status.humidity_percent))
        self._interface_labels["temp_alarm"].configure(text=str(status.temp_alarm))
        self._interface_labels["humidity_alarm"].configure(text=str(status.humidity_alarm))
        self._interface_labels["gas_raw"].configure(text=str(status.gas_raw))
        self._interface_labels["gas_voltage"].configure(
            text="None" if status.gas_voltage is None else f"{status.gas_voltage:.3f}"
        )
        self._interface_labels["gas_alarm"].configure(text=str(status.gas_alarm))
        self._interface_labels["motion_detected"].configure(text=str(status.motion_detected))
        self._interface_labels["safety_state"].configure(text=status.safety_state.value)
        self._interface_labels["sensor_fault"].configure(text=str(status.sensor_fault))
        health_text(self._interface_labels["temp_humidity_health"], status.temp_humidity_health)
        health_text(self._interface_labels["gas_health"], status.gas_health)
        health_text(self._interface_labels["motion_health"], status.motion_health)
        self._interface_labels["timestamp"].configure(text=status.timestamp.strftime("%H:%M:%S.%f")[:-3])
        self._interface_labels["power.is_display_awake()"].configure(text=str(display_awake))
        self._interface_labels["alarm.is_alarm_active()"].configure(text=str(alarm_active))

    def _drain_and_log_events(self) -> None:
        for event in drain_events():
            payload_text = "" if event.payload is None else f" {event.payload}"
            self._log(f"EVENT: {event.event_type.value}{payload_text}")
            self._interface_labels["last_event"].configure(text=f"{event.event_type.value}{payload_text}")

    def _log_local_transitions(self, status, alarm_active: bool) -> None:
        # Pure observation for the log - not a second decision-making path.
        if status.safety_state != self._prev_safety_state:
            self._log(f"Safety state -> {status.safety_state.name}")
            self._prev_safety_state = status.safety_state
        if self._alarm_driver.buzzer_on != self._prev_buzzer_on:
            self._log(f"Buzzer commanded {'ON' if self._alarm_driver.buzzer_on else 'OFF'}")
            self._prev_buzzer_on = self._alarm_driver.buzzer_on
        if self._alarm_driver.led_on != self._prev_led_on:
            self._log(f"LED commanded {'ON' if self._alarm_driver.led_on else 'OFF'}")
            self._prev_led_on = self._alarm_driver.led_on

    # ============================================================
    # SHUTDOWN
    # ============================================================
    def _on_close(self) -> None:
        self._environment_manager.stop()
        self._power_manager.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ManualTestApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
