#Runs settings calls without blocking touch screen inputs
from queue import Queue
from threading import Thread
import time


class SensorJobs:
    def __init__(self):
        self.events = Queue()
        self.busy = False
        self.started = 0.0
        self.handler = None
        self.warned = False
        self.warn_after = 5.0

    def start(self, function, handler, *, warn_after=5.0):
        if self.busy:
            raise RuntimeError('A sensor setting still running.')
        self.warn_after = warn_after
        self.busy = True
        self.started = time.monotonic()
        self.handler = handler
        self.warned = False

        def run():
            try:
                self.events.put((function(), None))
            except Exception as exc:
                self.events.put((None, str(exc)))
        Thread(target=run, daemon=True).start()
