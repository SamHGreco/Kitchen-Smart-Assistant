#Starts application
from __future__ import annotations
import argparse
from pathlib import Path
import signal
import tkinter as tk
from Input_Validation import load_config, read_preferences
from Demo_Data import create_demo
from App_Worker import Worker
from User_Interface import PantryWindow
ROOT = Path(__file__).resolve().parent

class InstanceLock:

    def __init__(self, path):
        self.handle = Path(path).open('a+b')
        try:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError('Grocery Touch is already running in this project.')

    def close(self):
        self.handle.close()
#sets initialized state
def run_app(
    settings,
    *,
    demo=False,
    serial_enabled=False,
    preferences_path=None,
    size='1024x600',
    fullscreen=False,
    sensors=None,
    read_scale=None,
    tare_scale=None,
    scale_controller=None,
    gas_calibration=None,
    drain_events=None,
    on_event=None
):
    temp = None
    lock = None
    root = None
    worker = None
    try:
        if demo:
            temp, settings = create_demo()
        preferences_path = Path(preferences_path or ROOT / 'pantry_preferences.json')
        preferences = read_preferences(preferences_path)
        if demo:
            preferences['idle_seconds'] = 10
        if not demo:
            lock = InstanceLock(ROOT / '.pantry-touch.lock')
        worker = Worker(
            settings,
            serial_enabled=serial_enabled,
            demo=demo,
            warning_days=preferences['expiry_warning_days']
        )
        root = tk.Tk()
        root.tk.call('tk', 'scaling', 1.15)
        w, h = map(int, size.lower().split('x'))
        if w < 800 or h < 480:
            raise ValueError('The tested minimum is 800x480 landscape.')
        w = min(w, root.winfo_screenwidth())
        h = min(h, root.winfo_screenheight())
        root.geometry(f'{w}x{h}+0+0')
        app = PantryWindow(
            root,
            worker,
            preferences,
            preferences_path,
            demo=demo,
            manual=not serial_enabled,
            sensors=sensors,
            fullscreen=fullscreen,
            read_scale=read_scale,
            tare_scale=tare_scale,
            scale_controller=scale_controller,
            gas_calibration=gas_calibration,
            drain_events=drain_events,
            on_event=on_event
        )
        signal.signal(signal.SIGINT, lambda *_: root.after(0, app.quit))
        signal.signal(signal.SIGTERM, lambda *_: root.after(0, app.quit))
        worker.start()
        root.mainloop()
    finally:
        if worker and worker.thread:
            worker.stop()
            worker.thread.join(timeout=20)
        if lock:
            lock.close()
        if temp:
            temp.cleanup()

def main():
    parser = argparse.ArgumentParser(description='Grocery touchscreen application')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--demo', action='store_true')
    mode.add_argument('--manual', action='store_true')
    mode.add_argument('--serial', action='store_true')
    parser.add_argument('--config', default=str(ROOT / 'config.pi.json'))
    parser.add_argument('--size', default='800x480')
    parser.add_argument('--fullscreen', action='store_true')
    args = parser.parse_args()
    settings = None if args.demo else load_config(args.config)
    run_app(settings, demo=args.demo, serial_enabled=args.serial, size=args.size, fullscreen=args.fullscreen)
if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Grocery stopped: ' + str(exc))
