"""Event types for the event-driven state machine.

Components push these events into the asyncio event queue. The state machine
pulls and reacts by transitioning between states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class EventType(IntEnum):
    """Enumeration of all event types the state machine can handle."""

    BOOTSTRAP_DONE = 1
    HEALTH_OK = 2
    HEALTH_FAIL = 3
    TUNNEL_DIED = 4
    SINGBOX_DIED = 5
    SHUTDOWN_REQUESTED = 6
    SERVER_CHANGE_REQUESTED = 7
    TIMEOUT = 8
    RESTART_REQUESTED = 9


@dataclass(frozen=True)
class VpnEvent:
    """An event posted to the state machine's event queue.

    Attributes:
        type: The event type.
        payload: Optional event-specific data.
    """

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
