"""Process watcher — supervises long-running child processes.

The daemon starts two long-lived children (sing-box and tun2socks) and must
notice when either of them dies: a dead tun2socks leaves tun0 down while the
catch-all rule still points at it, which blackholes the host.

This module owns that supervision. There is exactly one watcher per process
kind, so a process that is deliberately replaced (server switch, recovery) is
never mistaken for a crashed one — the previous watcher is cancelled at the
moment its handle becomes obsolete.
"""

from __future__ import annotations

import asyncio
import logging

from vpn.core.events import EventType, VpnEvent
from vpn.core.ports import PopenHandle

logger = logging.getLogger("vpn")

POLL_INTERVAL = 1.0  # seconds


class ProcessWatcher:
    """Watches child processes and posts a death event once per process.

    Args:
        events: Queue the state machine consumes its events from.
        interval: Seconds between liveness polls of each watched handle.
    """

    def __init__(
        self, events: asyncio.Queue[VpnEvent], *, interval: float = POLL_INTERVAL
    ) -> None:
        self._events = events
        self._interval = interval
        self._tasks: dict[EventType, asyncio.Task[None]] = {}

    @property
    def watched(self) -> list[EventType]:
        """Event types currently under supervision."""
        return sorted(self._tasks, key=int)

    def watch(self, event_type: EventType, handle: PopenHandle) -> None:
        """Start supervising *handle*, posting *event_type* when it exits.

        Any previous watcher for the same event type is cancelled first: the
        replaced process was stopped on purpose, so its exit must stay silent.

        Args:
            event_type: Death event to post (SINGBOX_DIED or TUNNEL_DIED).
            handle: Handle of the freshly started process.
        """
        self.unwatch(event_type)
        self._tasks[event_type] = asyncio.create_task(
            self._supervise(event_type, handle),
            name="watch-%s" % event_type.name.lower(),
        )
        logger.debug("Watching PID %d for %s", handle.pid, event_type.name)

    def unwatch(self, event_type: EventType) -> None:
        """Stop supervising a process kind without posting an event."""
        task = self._tasks.pop(event_type, None)
        if task is not None and not task.done():
            task.cancel()

    def stop(self) -> None:
        """Cancel every watcher — daemon shutdown."""
        for event_type in list(self._tasks):
            self.unwatch(event_type)

    async def _supervise(self, event_type: EventType, handle: PopenHandle) -> None:
        """Poll *handle* until it exits, then post the death event.

        Args:
            event_type: Event to post on exit.
            handle: Handle whose liveness is checked.
        """
        while True:
            await asyncio.sleep(self._interval)
            if handle.poll() is not None:
                break
        logger.error("Process PID %d exited — posting %s", handle.pid, event_type.name)
        await self._events.put(VpnEvent(event_type, {"pid": handle.pid}))
