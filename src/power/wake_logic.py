"""Pure wake-request decision logic used by PowerManager.

Kept separate from PowerManager's stateful bookkeeping (see sleep_manager.py)
so the "should the display wake right now" rule is easy to read and test in
isolation.
"""

from __future__ import annotations

from app.shared.models import UIState


def should_request_wake(safety_alarm_active: bool, activity_occurred: bool) -> bool:
    """Return True if the display should wake (or stay awake) right now.

    The display must wake immediately if a safety alarm is active, or if any
    activity source (touch, motion, barcode, weight) has just occurred.
    """
    return safety_alarm_active or activity_occurred


def should_request_sleep(
    ui_state: UIState,
    transaction_active: bool,
    safety_alarm_active: bool,
    inactivity_seconds: float,
    inactivity_timeout_seconds: float,
) -> bool:
    """Return True if the display should be put into power-saving mode now.

    Sleep is only allowed on the Home/Idle screen, with no active inventory
    transaction and no active safety alarm, after the inactivity timeout.
    """
    return (
        ui_state == UIState.HOME
        and not transaction_active
        and not safety_alarm_active
        and inactivity_seconds >= inactivity_timeout_seconds
    )
