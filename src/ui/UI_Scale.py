#Stand in


#Reads optional package weight
from __future__ import annotations
import math
from queue import Queue, Empty
from threading import Thread
import time
from UI_Widgets import Sheet, label, button, edit_text, MUTED, TEAL, RED


from Scale_Interface import ScaleReading


#Checks the scale response
def checked_grams(reading, now=None):
    if not isinstance(reading, ScaleReading):
        raise ValueError('The scale adapter must return ScaleReading.')
    if reading.unit != 'g':
        raise ValueError('The scale adapter must return grams.')
    if reading.stable is not True:
        raise ValueError('Weight is moving. Wait, then tap Read again.')
    if isinstance(reading.grams, bool) or not isinstance(reading.grams, (int, float)):
        raise ValueError('The scale did not return a numeric weight.')
    grams = float(reading.grams)
    if not math.isfinite(grams) or grams <= 0:
        raise ValueError('Place one item on the scale, then try again.')
    stamp = reading.sampled_at
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
        raise ValueError('The scale measurement needs a valid timestamp.')
    age = (time.time() if now is None else now) - stamp
    if age < -1 or age > 5:
        raise ValueError('The scale reading is old. Request a fresh measurement.')
    return grams


#Provides a demo measurement
def demo_read_scale():
    return ScaleReading(375.0, True, time.time())


#Runs one scale request at a time
class ScaleTask:
    def __init__(self, reader=None, timeout=8.0, *, tare=None):
        self.reader = reader
        self.tare = tare
        self.operation = 'read'
        self.timeout = timeout
        self.events = Queue()
        self.thread = None
        self.token = None
        self.generation = 0
        self.deadline = 0.0

    def start(self):
        if self.reader is None:
            raise ValueError('Scale not connected. Keep the weight or enter it manually.')
        self._start(lambda: checked_grams(self.reader()), 'read')

    #Calls the existing WeightSensor.tare
    def start_tare(self):
        if self.tare is None:
            raise ValueError('Scale not connected. Tare is unavailable.')

        def apply():
            result = self.tare()
            if result is False:
                raise RuntimeError('The scale reported that tare failed.')
            return True
        self._start(apply, 'tare')

    def _start(self, function, operation):
        if self.thread and self.thread.is_alive():
            raise ValueError('The previous scale request is still finishing. Try again later.')
        self.operation = operation
        self.generation += 1
        token = self.generation
        self.token = token
        self.deadline = time.monotonic() + self.timeout

        def run():
            try:
                value, error = function(), None
            except Exception as exc:
                value, error = None, str(exc) or 'The scale request failed.'
            self.events.put((token, value, error, time.monotonic()))

        self.thread = Thread(target=run, name='grocery-scale', daemon=True)
        self.thread.start()

    def timeout_message(self):
        if self.operation == 'tare':
            return 'Tare timed out and may finish later. Check the scale before weighing.'
        return 'Scale timed out. Existing weight was kept.'

    def poll(self):
        while True:
            try:
                token, grams, error, completed = self.events.get_nowait()
            except Empty:
                break
            if token == self.token:
                self.token = None
                if completed > self.deadline:
                    return None, self.timeout_message()
                return grams, error
        if self.token is not None and time.monotonic() >= self.deadline:
            self.token = None
            return None, self.timeout_message()
        return None

    def cancel(self):
        self.token = None


#Prevents copying one measured load into several packages
def check_scale_quantity(owner, values):
    measured = getattr(owner, 'scale_weight', None)
    if measured is not None and values['item_weight'].get() == measured:
        if str(values.get('quantity').get()).strip() != '1':
            raise ValueError('A scale reading is for one package. Set quantity to 1, or use manual per-package weight.')


#Adds the optional weight question
def ask_scale(app, owner, value, quantity=None):
    if owner.closed or app.closing:
        return None
    previous = getattr(app, 'weight_prompt', None)
    if previous is not None:
        previous.close()
    prompt = ScalePrompt(app, owner, value, quantity)
    app.weight_prompt = prompt
    return prompt


class ScalePrompt:
    def __init__(self, app, owner, value, quantity=None):
        self.app = app
        self.owner = owner
        self.value = value
        self.quantity = quantity
        self.task = app.scale_task
        self.grams = None
        self.waiting = False
        self.timer = None
        self.sheet = Sheet(app, 'Update weight from scale?', self.close)
        current = value.get().strip()
        self.sheet.close_button.config(text='Keep weight' if current else 'Skip')
        label(self.sheet.body, 'Read this package from the scale?', 24, True,
              wraplength=700).pack(pady=(22, 8))
        label(self.sheet.body, f"Current weight: {current + ' g' if current else 'not entered'}",
              16, fg=MUTED).pack(pady=6)
        self.readout = label(self.sheet.body, '-- g', 38, True, fg=TEAL)
        self.readout.pack(pady=8)
        info = ('DEMO: simulated 375 g. No hardware is read.' if app.demo else
                'Place one package on the scale. Nothing is saved yet.')
        if self.task.reader is None:
            info = 'Scale not connected. Keep the weight or enter it manually.'
        self.note = label(self.sheet.body, info, 13, fg=MUTED, wraplength=690)
        self.note.pack(padx=15, pady=8)
        button(self.sheet.footer, 'Keep weight' if current else 'Skip', self.close).pack(side='left')
        button(self.sheet.footer, 'Enter manually', self.manual).pack(side='left', padx=5)
        self.use_button = button(self.sheet.footer, 'Use weight', self.use, primary=True)
        self.use_button.pack(side='right')
        self.use_button.config(state='disabled')
        self.read_button = button(self.sheet.footer, 'Yes - read scale', self.read)
        self.read_button.pack(side='right', padx=5)
        self.timer = app.root.after(80, self.poll)

    def valid_owner(self):
        return not self.owner.closed and not self.app.closing

    def one_package(self):
        if self.quantity is not None and self.quantity.get().strip() != '1':
            raise ValueError('Set quantity to 1 before weighing. Weigh each package separately.')

    def read(self):
        if self.waiting or not self.valid_owner():
            return
        self.grams = None
        self.readout.config(text='-- g')
        self.use_button.config(state='disabled')
        try:
            self.one_package()
            if getattr(getattr(self.app, 'sensor_jobs', None), 'busy', False):
                raise ValueError('Wait for the calibration or settings operation to finish.')
            self.task.start()
        except ValueError as exc:
            self.note.config(text=str(exc), fg=RED)
            return
        self.waiting = True
        self.read_button.config(state='disabled')
        self.note.config(text='Reading scale... Keep / Skip is still available.', fg=MUTED)

    def poll(self):
        self.timer = None
        if self.sheet.closed:
            return
        if not self.valid_owner():
            self.close()
            return
        if self.waiting:
            result = self.task.poll()
            if result is not None:
                self.waiting = False
                self.grams, error = result
                self.read_button.config(state='normal', text='Read again')
                if error:
                    self.note.config(text=error, fg=RED)
                else:
                    self.readout.config(text=f'{self.grams:g} g')
                    message = 'DEMO reading. ' if self.app.demo else ''
                    self.note.config(text=message + 'Tap Use weight, then Add or Save on the form.', fg=TEAL)
                    self.use_button.config(state='normal')
        self.timer = self.app.root.after(80, self.poll)

    def use(self):
        if self.waiting or self.grams is None or not self.valid_owner():
            return
        try:
            self.one_package()
        except ValueError as exc:
            self.note.config(text=str(exc), fg=RED)
            return
        text = f'{self.grams:g}'
        self.value.set(text)
        self.owner.scale_weight = text
        self.close()

    def manual(self):
        if not self.valid_owner():
            self.close()
            return
        self.owner.scale_weight = None
        self.close()
        edit_text(self.app, 'Weight in grams (one package)', self.value, numeric=True)

    def close(self):
        if self.sheet.closed:
            return
        self.task.cancel()
        if self.timer is not None:
            self.app.root.after_cancel(self.timer)
            self.timer = None
        if getattr(self.app, 'weight_prompt', None) is self:
            self.app.weight_prompt = None
        self.sheet.close()


#To complete testing without hardware
def demo_tare():
    return None


#Asks before zeroing the scale
def ask_tare(app, owner):
    if owner.closed or app.closing:
        return None
    if getattr(app, 'weight_prompt', None) is not None:
        return None
    previous = getattr(app, 'tare_prompt', None)
    if previous is not None:
        previous.close()
    prompt = TarePrompt(app, owner)
    app.tare_prompt = prompt
    return prompt


class TarePrompt:
    def __init__(self, app, owner):
        self.app = app
        self.owner = owner
        self.task = app.scale_task
        self.waiting = False
        self.timer = None
        self.sheet = Sheet(app, 'Tare scale', self.close)
        label(self.sheet.body, 'Zero the scale?', 28, True).pack(pady=(20, 12))
        label(self.sheet.body,
              'Remove the item. Leave only the empty container you want to zero.',
              17, wraplength=670).pack(padx=20, pady=10)
        label(self.sheet.body,
              'Tare changes the zero reference, not calibration.\nSaved item weights and inventory will not change.',
              13, fg=MUTED, wraplength=670).pack(padx=20, pady=10)
        info = 'Calls tare() once on your connected WeightSensor.'
        if self.app.demo:
            info = 'DEMO: simulated tare. No hardware is changed.'
        elif self.task.tare is None:
            info = 'Scale not connected. Tare is unavailable.'
        self.note = label(self.sheet.body, info, 14, fg=MUTED, wraplength=670)
        self.note.pack(padx=20, pady=10)
        self.close_button = button(self.sheet.footer, 'Cancel', self.close)
        self.close_button.pack(side='left')
        self.apply_button = button(self.sheet.footer, 'Tare now', self.apply, primary=True)
        self.apply_button.pack(side='right')
        if self.task.tare is None:
            self.apply_button.config(state='disabled')
        self.timer = app.root.after(80, self.poll)

    def apply(self):
        if self.waiting or self.sheet.closed or self.owner.closed or self.app.closing:
            return
        try:
            if getattr(getattr(self.app, 'sensor_jobs', None), 'busy', False):
                raise ValueError('Wait for the calibration or settings operation to finish.')
            self.task.start_tare()
        except ValueError as exc:
            self.note.config(text=str(exc), fg=RED)
            return
        self.waiting = True
        self.apply_button.config(state='disabled')
        self.close_button.config(text='Close')
        self.sheet.close_button.config(text='Close')
        self.note.config(text='Taring... Closing this screen cannot undo a sent tare.', fg=MUTED)

    def poll(self):
        self.timer = None
        if self.sheet.closed:
            return
        if self.app.closing or self.owner.closed:
            self.close()
            return
        if self.waiting:
            result = self.task.poll()
            if result is not None:
                self.waiting = False
                _, error = result
                if error:
                    self.note.config(text=error, fg=RED)
                    self.apply_button.config(text='Retry tare', state='normal')
                else:
                    text = ('Demo tare complete.' if self.app.demo else
                            'Tare call finished. Check the scale reads zero before weighing.')
                    self.note.config(text=text, fg=TEAL)
                    self.close_button.config(text='Done')
        self.timer = self.app.root.after(80, self.poll)

    def close(self):
        if self.sheet.closed:
            return
        if self.waiting:
            self.task.cancel()
        if self.timer is not None:
            self.app.root.after_cancel(self.timer)
            self.timer = None
        if getattr(self.app, 'tare_prompt', None) is self:
            self.app.tare_prompt = None
        self.sheet.close()
