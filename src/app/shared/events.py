"""Thread-safe event output channel from the environment/safety subsystem to
the rest of the application (primarily the GUI).

Producers (sensor/manager threads) call `publish_event()`. Consumers (e.g.
the GUI main loop) call `get_event_queue().get(...)` to drain events. Do not
reach into subsystem internals to detect state changes - listen for events.
"""

from __future__ import annotations

import queue
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(Enum):
    MOTION_DETECTED = "motion_detected"
    GAS_ALARM_STARTED = "gas_alarm_started"
    GAS_ALARM_CLEARED = "gas_alarm_cleared"
    ENVIRONMENT_SENSOR_FAULT = "environment_sensor_fault"
    ENVIRONMENT_SENSOR_RECOVERED = "environment_sensor_recovered"
    WAKE_REQUEST = "wake_request"


@dataclass(frozen=True)
class Event:
    event_type: EventType
    timestamp: datetime
    payload: dict[str, Any] | None = None


_event_queue: "queue.Queue[Event]" = queue.Queue()


def get_event_queue() -> "queue.Queue[Event]":
    """Return the shared, thread-safe event queue. Safe to call from any thread."""
    return _event_queue


def publish_event(event_type: EventType, payload: dict[str, Any] | None = None) -> Event:
    """Build an Event and push it onto the shared queue. Thread-safe."""
    event = Event(event_type=event_type, timestamp=datetime.now(timezone.utc), payload=payload)
    _event_queue.put(event)
    return event


def drain_events() -> list[Event]:
    """Return all events currently queued, without blocking.

    Convenient for a GUI main loop to call once per frame instead of
    blocking on `get_event_queue().get()`.
    """
    events: list[Event] = []
    while True:
        try:
            events.append(_event_queue.get_nowait())
        except queue.Empty:
            break
    return events
