#Stand in

"""Calibration screens. Blocking samples run in Background_Jobs, never in Tk."""
from __future__ import annotations
import tkinter as tk
from dataclasses import asdict
from Sensor_Interfaces import GasSettings
from UI_Widgets import Sheet, label, button, touch_field, CARD, MUTED, TEAL, RED, FONT


class _CalibrationScreens:
    def _calibration_job(self, sheet, note, controls, function, describe, *, warn_after=5):
        if self.scale_task.thread and self.scale_task.thread.is_alive():
            note.config(text='Wait for the current scale read or tare to finish.', fg=RED)
            return

        def done(result, error):
            if sheet.closed or self.closing:
                return
            for control in controls:
                control.config(state='normal')
            note.config(text=error or describe(result), fg=RED if error else TEAL)

        try:
            self.sensor_jobs.start(function, done, warn_after=warn_after)
        except RuntimeError as exc:
            note.config(text=str(exc), fg=RED)
            return
        for control in controls:
            control.config(state='disabled')
        note.config(text='Working... Closing this screen does not cancel a sent operation.', fg=MUTED)

    def show_scale_calibration(self):
        sheet = Sheet(self, 'Scale calibration')
        controller = self.scale_controller
        label(sheet.body, '1. Empty platform   2. Known mass   3. Verify', 19, True).pack(pady=(14, 5))
        label(sheet.body, 'Remove everything, capture zero, then place a known calibration mass.\n'
              'Enter its actual mass in grams. Calibrating does not change saved inventory.',
              12, fg=MUTED, wraplength=700, justify='left').pack(padx=15, pady=5)
        form = tk.Frame(sheet.body, bg=CARD)
        form.pack(fill='x', padx=20, pady=5)
        form.columnconfigure(0, weight=1)
        mass = tk.StringVar(value='500')
        touch_field(self, form, 'Known mass (grams)', mass, 0, numeric=True)
        info = ('DEMO' if self.demo else
                "")
        if controller is None:
            info = 'No calibration controller connected.'
        note = label(sheet.body, info, 12, fg=MUTED, wraplength=700, justify='left')
        note.pack(padx=15, pady=12)
        controls = []
        zero = button(sheet.footer, '1. Capture empty zero', lambda: self._calibration_job(
            sheet, note, controls, controller.capture_zero, str))
        zero.pack(side='left')
        def save_known_mass():
            entered_mass = mass.get()
            self._calibration_job(
                sheet, note, controls, lambda: controller.calibrate(entered_mass),
                lambda result: f"{'DEMO ' if self.demo else ''}Calibration saved: {result['counts_per_gram']:.6g} counts/g. "
                               'Remove the mass and verify zero, then test a second known mass.')

        save = button(sheet.footer, '2. Save known mass', save_known_mass, primary=True)
        save.pack(side='right')
        controls.extend((zero, save))
        if controller is None:
            for control in controls:
                control.config(state='disabled')

    def show_gas_calibration(self):
        sheet = Sheet(self, 'MQ-4 calibration / startup tuning')
        service = self.gas_calibration
        left = tk.Frame(sheet.body, bg=CARD)
        left.pack(side='left', fill='both', expand=True, padx=12, pady=10)
        right = tk.Frame(sheet.body, bg=CARD)
        right.pack(side='right', fill='both', expand=True, padx=12, pady=10)
        label(left, 'Clean-air baseline', 17, True).pack(anchor='w')
        label(left, '', 11, fg=MUTED, wraplength=325,
              justify='left').pack(anchor='w', pady=8)
        clean, warm = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        for text, variable in [('Known clean air confirmed', clean),
                               ('Conditioning / warm-up complete', warm)]:
            tk.Checkbutton(left, text=text, variable=variable, bg=CARD, font=(FONT, 11),
                           anchor='w', wraplength=315, justify='left').pack(anchor='w', pady=5)
        note = label(left, '' if service is None else
                     'Baseline capture takes about 12 seconds.\nMonitoring continues independently.',
                     11, fg=MUTED, wraplength=320, justify='left')
        note.pack(anchor='w', pady=8)
        label(right, 'Thresholds for next launch', 17, True).pack(anchor='w')
        values = GasSettings(1.5, 0.15, 3.0)
        load_error = None
        if service:
            try:
                values = service.startup_settings(values)
            except Exception as exc:
                load_error = str(exc)
                note.config(text=load_error, fg=RED)
        variables = {key: tk.StringVar(value=str(value)) for key, value in asdict(values).items()}
        form = tk.Frame(right, bg=CARD)
        form.pack(fill='x', pady=5)
        form.columnconfigure(0, weight=1)
        for row, (key, caption) in enumerate([('threshold_voltage', 'Threshold (ADC volts)'),
                                              ('hysteresis_voltage', 'Hysteresis (volts)'),
                                              ('debounce_seconds', 'Debounce (seconds)')]):
            touch_field(self, form, caption, variables[key], row, numeric=True)
        label(right, '',
              10, fg=RED, wraplength=325, justify='left').pack(anchor='w', pady=3)
        controls = []
        def capture_baseline():
            clean_air, warmed_up = clean.get(), warm.get()
            self._calibration_job(
                sheet, note, controls,
                lambda: service.capture_baseline(clean_air_confirmed=clean_air, warmup_confirmed=warmed_up),
                lambda result: f"Saved {result['samples']} samples; mean {result['mean_voltage']:.4f} V. NOT ppm.",
                warn_after=20)

        def save_thresholds():
            entered_values = {key: variable.get() for key, variable in variables.items()}
            self._calibration_job(
                sheet, note, controls, lambda: service.save_startup(entered_values),
                lambda result: 'Startup tuning saved. Restart Team_Launcher in a controlled test to apply it.')

        capture = button(sheet.footer, 'Capture baseline', capture_baseline)
        capture.pack(side='left')
        save = button(sheet.footer, 'Save for next launch', save_thresholds, primary=True)
        save.pack(side='right')
        controls.extend((capture, save))
        if service is None or load_error:
            for control in controls:
                control.config(state='disabled')
