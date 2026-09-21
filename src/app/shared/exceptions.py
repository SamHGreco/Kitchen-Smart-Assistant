"""Shared exception types used across the environment / power subsystem."""

from __future__ import annotations


class SensorReadError(Exception):
    """Raised by a hardware driver when a single sensor read fails.

    Callers must catch this, log it, and update sensor health instead of
    crashing the monitoring thread or substituting a fabricated reading.
    """
