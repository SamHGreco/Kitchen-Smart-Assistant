"""
Standalone DOUT monitor, bypasses HX711_Driver for testing. Watches
the raw pin and logs every transition with a timestamp. Shows directly
whether (and how often) the chip is actually signaling ready.
Ctrl+C to stop.
"""

import time
import RPi.GPIO as GPIO

DOUT_PIN = 5
SCK_PIN = 6

GPIO.setmode(GPIO.BCM)
GPIO.setup(DOUT_PIN, GPIO.IN)
GPIO.setup(SCK_PIN, GPIO.OUT)
GPIO.output(SCK_PIN, GPIO.LOW)  # must stay low to keep the chip converting, not asleep

print("Watching DOUT. LOW = chip signaling 'data ready'. Ctrl+C to stop.\n")

last_state = GPIO.input(DOUT_PIN)
last_change = time.monotonic()
print(f"Starting state: {'LOW (ready)' if last_state == GPIO.LOW else 'HIGH (busy)'}")

try:
    while True:
        state = GPIO.input(DOUT_PIN)
        if state != last_state:
            now = time.monotonic()
            duration = now - last_change
            label = 'LOW (ready)' if state == GPIO.LOW else 'HIGH (busy)'
            print(f"[{now:.3f}] -> {label}   (previous state held for {duration*1000:.1f} ms)")
            last_state = state
            last_change = now
except KeyboardInterrupt:
    print("\nStopped.")
finally:
    GPIO.cleanup((DOUT_PIN, SCK_PIN))
