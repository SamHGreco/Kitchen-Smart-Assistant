"""PowerManager: decides when the touchscreen should sleep or wake (Phase 7).

Tracks activity/UI-state inputs from the rest of the team and exposes
`is_display_awake()` plus a `WAKE_REQUEST` event, rather than directly
issuing 52Pi display commands - this keeps power logic independent of the
UI/display implementation (owned by the UI subsystem).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from app import config
from app.shared.events import EventType, publish_event
from app.shared.models import ActivityType, UIState
from power.wake_logic import should_request_sleep, should_request_wake

logger = logging.getLogger(__name__)


class PowerManager:
    """Tracks activity/UI state and decides display sleep/wake requests.

    Public API (safe for other subsystems/threads to call):
        start(), stop(), notify_activity(activity_type), set_ui_state(state),
        set_transaction_active(active), set_safety_alarm_active(active),
        is_display_awake()
    """

    def __init__(
        self,
        inactivity_timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        self._inactivity_timeout_seconds = (
            inactivity_timeout_seconds
            if inactivity_timeout_seconds is not None
            else config.UI_INACTIVITY_TIMEOUT_SECONDS
        )
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else config.POWER_MANAGER_POLL_INTERVAL_SECONDS
        )

        self._lock = threading.Lock()
        self._last_activity_time = datetime.now(timezone.utc)
        self._display_awake = True
        self._transaction_active = False
        self._ui_state = UIState.HOME
        self._safety_alarm_active = False

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background inactivity-timeout thread. No-op if already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="PowerManager", daemon=True)
        self._thread.start()
        logger.info(
            "Power manager started (inactivity timeout=%.0fs)", self._inactivity_timeout_seconds
        )

    def stop(self) -> None:
        """Signal the background thread to exit. Blocks briefly."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval_seconds + 1.0)
            self._thread = None
        logger.info("Power manager stopped")

    def notify_activity(self, activity_type: ActivityType) -> None:
        """Record activity from any source (touch, motion, barcode, weight)."""
        with self._lock:
            self._last_activity_time = datetime.now(timezone.utc)
            needs_wake = should_request_wake(
                self._safety_alarm_active, activity_occurred=True
            ) and not self._display_awake
            self._display_awake = True
        logger.debug("Activity: %s", activity_type.value)
        if needs_wake:
            self._request_wake()

    def set_ui_state(self, state: UIState) -> None:
        """Report the GUI's current coarse UI state (only HOME matters for sleep)."""
        with self._lock:
            self._ui_state = state

    def set_transaction_active(self, active: bool) -> None:
        """Report whether an inventory transaction is in progress (blocks sleep)."""
        with self._lock:
            self._transaction_active = active

    def set_safety_alarm_active(self, active: bool) -> None:
        """Report the current overall safety alarm state (from EnvironmentManager)."""
        with self._lock:
            changed = active != self._safety_alarm_active
            self._safety_alarm_active = active
            if active:
                self._last_activity_time = datetime.now(timezone.utc)
            needs_wake = should_request_wake(active, activity_occurred=False) and not self._display_awake
            if active:
                self._display_awake = True
        if changed:
            logger.info("Safety alarm active=%s", active)
        if needs_wake:
            self._request_wake()

    def is_display_awake(self) -> bool:
        """Current display power state. False means sleep has been requested."""
        with self._lock:
            return self._display_awake

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._evaluate_sleep()
            self._stop_event.wait(self._poll_interval_seconds)

    def _evaluate_sleep(self) -> None:
        with self._lock:
            if not self._display_awake:
                return
            inactivity_seconds = (
                datetime.now(timezone.utc) - self._last_activity_time
            ).total_seconds()
            go_to_sleep = should_request_sleep(
                self._ui_state,
                self._transaction_active,
                self._safety_alarm_active,
                inactivity_seconds,
                self._inactivity_timeout_seconds,
            )
            if go_to_sleep:
                self._display_awake = False
        if go_to_sleep:
            logger.info("Display sleep requested (inactivity timeout)")

    def _request_wake(self) -> None:
        logger.info("Display wake requested")
        publish_event(EventType.WAKE_REQUEST)
