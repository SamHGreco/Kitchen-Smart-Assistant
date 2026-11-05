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
        sheet = Sheet(self, 'MQ-4 Gas Sensor Calibration')
        service = self.gas_calibration

        label(
            sheet.body,
            'Clean-Air Baseline Calibration',
            19,
            True
        ).pack(pady=(15, 8))

        label(
            sheet.body,
            'This calibration records the current MQ-4 voltage, '
            'temperature, and humidity as the new baseline. '
            'The gas alarm threshold is calculated automatically '
            'and saved for future application launches.',
            12,
            fg=MUTED,
            wraplength=680,
            justify='left'
        ).pack(padx=20, pady=8)

        clean_air = tk.BooleanVar(value=False)
        warmed_up = tk.BooleanVar(value=False)

        tk.Checkbutton(
            sheet.body,
            text='I confirm the sensor is in clean air.',
            variable=clean_air,
            bg=CARD,
            font=(FONT, 12),
            anchor='w'
        ).pack(anchor='w', padx=25, pady=5)

        tk.Checkbutton(
            sheet.body,
            text='I confirm the sensor has completed warm-up.',
            variable=warmed_up,
            bg=CARD,
            font=(FONT, 12),
            anchor='w'
        ).pack(anchor='w', padx=25, pady=5)

        status_label = label(
            sheet.body,
            '',
            12,
            fg=MUTED,
            wraplength=680,
            justify='left'
        )
        status_label.pack(padx=20, pady=12)

        note = label(
            sheet.body,
            '',
            12,
            fg=MUTED,
            wraplength=680,
            justify='left'
        )
        note.pack(padx=20, pady=10)

        def display_status(status):
            if not status.is_calibrated:
                status_label.config(
                    text='Status: Not calibrated'
                )
                return

            text = (
                f'Baseline: {status.baseline_voltage:.3f} V\n'
                f'Alarm threshold: '
                f'{status.alarm_threshold_voltage:.3f} V'
            )

            if status.recalibration_needed:
                text += '\nRecalibration recommended.'

            status_label.config(text=text)

        if service is None:
            note.config(
                text='Environmental manager not connected.',
                fg=RED
            )
        else:
            try:
                display_status(
                    service.get_gas_calibration_status()
                )
            except Exception as exc:
                note.config(text=str(exc), fg=RED)

        controls = []

        def perform_calibration():
            if not clean_air.get() or not warmed_up.get():
                note.config(
                    text='Confirm clean air and sensor warm-up '
                         'before calibrating.',
                    fg=RED
                )
                return

            def calibrate():
                result = service.calibrate_gas_sensor()

                if not result.success:
                    raise RuntimeError(result.message)

                return result

            def describe(result):
                display_status(result.status)

                return (
                    f'{result.message}\n'
                    f'Baseline: '
                    f'{result.status.baseline_voltage:.3f} V\n'
                    f'Alarm threshold: '
                    f'{result.status.alarm_threshold_voltage:.3f} V'
                )

            self._calibration_job(
                sheet,
                note,
                controls,
                calibrate,
                describe,
                warn_after=5
            )

        capture_button = button(
            sheet.footer,
            'Capture Baseline',
            perform_calibration,
            primary=True
        )

        capture_button.pack(side='right')
        controls.append(capture_button)

        if service is None:
            capture_button.config(state='disabled')

    def show_calibration(self):
        sheet = Sheet(self, 'Calibrate', compact=True)
        label(sheet.body, 'Calibrate', 16, True).pack(anchor='w', padx=14, pady=(8, 4))
        content = tk.Frame(sheet.body, bg=CARD)
        content.pack(fill='both', expand=True, padx=12, pady=2)
        content.columnconfigure(0, weight=1, uniform='calibrate')
        content.columnconfigure(1, weight=1, uniform='calibrate')
        left = tk.Frame(content, bg=CARD)
        right = tk.Frame(content, bg=CARD)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        right.grid(row=0, column=1, sticky='nsew')
        label(left, 'Scale calibration', 14, True).pack(anchor='w')
        label(left, '1. Empty platform: capture zero.\n2. Add a known mass and save its grams.',
              11, fg=MUTED, wraplength=320, justify='left').pack(anchor='w', pady=4)
        controller = self.scale_controller
        mass = tk.StringVar(value='500')
        form = tk.Frame(left, bg=CARD)
        form.pack(fill='x')
        form.columnconfigure(0, weight=1)
        touch_field(self, form, 'Known mass (grams)', mass, 0, numeric=True)
        actions = tk.Frame(left, bg=CARD)
        actions.pack(fill='x', padx=8, pady=4)
        note = label(left, 'Verify zero and a second known mass after saving.',
                     10, fg=MUTED, wraplength=320, justify='left')
        controls = []
        zero = button(actions, 'Capture zero', lambda: self._calibration_job(
            sheet, note, controls, controller.capture_zero, str))
        zero.config(font=(FONT, 11, 'bold'), padx=8, pady=8)
        zero.pack(side='left', padx=(0, 5))

        def save_mass():
            entered_mass = mass.get()
            self._calibration_job(sheet, note, controls,
                lambda: controller.calibrate(entered_mass),
                lambda result: f"Saved: {result['counts_per_gram']:.6g} counts/g. "
                               'Verify empty zero and a second known mass.')
        save = button(actions, 'Save mass', save_mass, primary=True)
        save.config(font=(FONT, 11, 'bold'), padx=8, pady=8)
        save.pack(side='left')
        note.pack(anchor='w', padx=9, pady=5)
        if controller is None:
            note.config(text='No scale calibration controller connected.', fg=RED)
            zero.config(state='disabled')
            save.config(state='disabled')
        else:
            controls.extend((zero, save))

        service = self.gas_calibration
        label(right, 'Gas calibration', 14, True).pack(anchor='w')
        label(right, 'Capture a clean-air baseline only.\nThe controller calculates the alarm threshold.',
              11, fg=MUTED, wraplength=320, justify='left').pack(anchor='w', pady=4)
        clean_air = tk.BooleanVar(value=False)
        warmed_up = tk.BooleanVar(value=False)
        tk.Checkbutton(right, text='I confirm clean air.', variable=clean_air,
                       bg=CARD, font=(FONT, 11), pady=3).pack(anchor='w')
        tk.Checkbutton(right, text='Sensor warm-up is complete.', variable=warmed_up,
                       bg=CARD, font=(FONT, 11), pady=3).pack(anchor='w')
        status_label = label(right, '', 10, fg=MUTED, wraplength=320, justify='left')
        status_label.pack(anchor='w', pady=4)
        gas_note = label(right, '', 10, fg=MUTED, wraplength=320, justify='left')

        def display_status(status):
            if not status.is_calibrated:
                text = 'Not calibrated'
            else:
                text = (f'Baseline: {status.baseline_voltage:.3f} V\n'
                        f'Alarm threshold: {status.alarm_threshold_voltage:.3f} V')
                if status.recalibration_needed:
                    text += ' - recalibrate'
            status_label.config(text=text)

        def capture_baseline():
            if not clean_air.get() or not warmed_up.get():
                gas_note.config(text='Confirm clean air and warm-up before calibrating.', fg=RED)
                return

            def calibrate():
                result = service.calibrate_gas_sensor()
                if not result.success:
                    raise RuntimeError(result.message)
                return result

            def describe(result):
                display_status(result.status)
                return result.message

            self._calibration_job(sheet, gas_note, controls, calibrate, describe, warn_after=5)

        capture = button(right, 'Capture gas baseline', capture_baseline, primary=True)
        capture.config(font=(FONT, 11, 'bold'), padx=8, pady=8)
        capture.pack(anchor='w', pady=4)
        gas_note.pack(anchor='w', pady=4)
        if service is None:
            capture.config(state='disabled')
            gas_note.config(text='Environmental manager not connected.', fg=RED)
        else:
            controls.append(capture)
            try:
                display_status(service.get_gas_calibration_status())
            except Exception as exc:
                gas_note.config(text=str(exc), fg=RED)
