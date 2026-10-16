"""Tests for the process watcher that supervises sing-box and tun2socks."""

from __future__ import annotations

import asyncio

import pytest

from vpn.core.events import EventType, VpnEvent
from vpn.core.health.process_watcher import ProcessWatcher
from vpn.core.ports import PopenHandle


def _handle(poll_values: list[int | None], pid: int = 4242) -> PopenHandle:
    """Build a fake handle whose poll() walks through *poll_values*."""
    state = {"i": 0}

    def poll() -> int | None:
        value = poll_values[min(state["i"], len(poll_values) - 1)]
        state["i"] += 1
        return value

    return PopenHandle(pid=pid, poll=poll, terminate=lambda: None, kill=lambda: None, wait=lambda _t: 0)


class TestProcessWatcher:
    @pytest.mark.asyncio
    async def test_posts_death_event_once(self) -> None:
        events: asyncio.Queue[VpnEvent] = asyncio.Queue()
        watcher = ProcessWatcher(events, interval=0.01)
        watcher.watch(EventType.TUNNEL_DIED, _handle([None, None, 1]))
        event = await asyncio.wait_for(events.get(), timeout=2)
        assert event.type == EventType.TUNNEL_DIED
        assert event.payload["pid"] == 4242
        watcher.stop()

    @pytest.mark.asyncio
    async def test_replacing_a_process_stays_silent(self) -> None:
        """A deliberately replaced process must not look like a crash."""
        events: asyncio.Queue[VpnEvent] = asyncio.Queue()
        watcher = ProcessWatcher(events, interval=0.01)
        dead = _handle([1], pid=1)
        watcher.watch(EventType.TUNNEL_DIED, dead)
        watcher.watch(EventType.TUNNEL_DIED, _handle([None], pid=2))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(events.get(), timeout=0.2)
        assert watcher.watched == [EventType.TUNNEL_DIED]
        watcher.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_every_watcher(self) -> None:
        events: asyncio.Queue[VpnEvent] = asyncio.Queue()
        watcher = ProcessWatcher(events, interval=0.01)
        watcher.watch(EventType.TUNNEL_DIED, _handle([None]))
        watcher.watch(EventType.SINGBOX_DIED, _handle([None]))
        assert watcher.watched == [EventType.TUNNEL_DIED, EventType.SINGBOX_DIED]
        watcher.stop()
        assert watcher.watched == []
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(events.get(), timeout=0.1)
