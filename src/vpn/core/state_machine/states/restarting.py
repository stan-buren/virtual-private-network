"""Restarting state — one deliberate restart, one verification, no ladder.

Used by the operator command `vpn restart` and by a manual server change.
There is no rotation, no subscription refresh and no repeated attempt: the
daemon replaces the tunnel processes once, checks that traffic flows, and
reports the result.
"""

from __future__ import annotations

import asyncio
import logging

from vpn.core import obs
from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")

RECOVERY_TIMEOUT = 90  # seconds


class RestartingState(VpnState):
    """Restart the tunnel processes once and verify the result."""

    _timeout_task: asyncio.Task[None] | None = None

    async def on_enter(self) -> None:
        self.ctx.recovery_count += 1
        logger.info("Entering RESTARTING state — manual restart")
        self._timeout_task = asyncio.create_task(self._on_timeout())
        asyncio.create_task(self._restart_tunnel())

    async def on_exit(self) -> None:
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None

    async def handle(self, event: VpnEvent) -> None:
        if event.type == EventType.BOOTSTRAP_DONE:
            await self.transition_to(
                __import__("vpn.core.state_machine.states.healthy", fromlist=["HealthyState"]).HealthyState
            )
        elif event.type == EventType.TIMEOUT:
            self.ctx.last_error = "Restart timed out after %ds" % RECOVERY_TIMEOUT
            logger.error(self.ctx.last_error)
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
        elif event.type == EventType.SHUTDOWN_REQUESTED:
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
        elif event.type in (EventType.TUNNEL_DIED, EventType.SINGBOX_DIED):
            # A death during a deliberate restart is expected: the old process
            # was just killed. Only log it, never escalate.
            obs.emit(
                "L0",
                "info",
                "none",
                error_class="process_exited_during_restart",
                process=event.type.name,
            )

    async def _restart_tunnel(self) -> None:
        """Restart once, verify once, report the truth."""
        orchestrator = getattr(self.machine, "_orchestrator", None)
        events = self.machine._event_queue
        if orchestrator is None:
            self.ctx.last_error = "No orchestrator available for restart"
            await events.put(VpnEvent(type=EventType.TIMEOUT))
            return

        started = obs.now()
        try:
            await orchestrator.restart_tunnel(self.ctx)
            ok = await orchestrator.verify_tunnel()
        except Exception as exc:
            obs.emit(
                "L0",
                "fail",
                "tunnel.restart",
                cost="restart",
                latency_ms=(obs.now() - started) * 1000,
                error_class="restart_exception",
                error=str(exc)[:300],
            )
            ok = False

        if ok:
            obs.emit(
                "L1",
                "ok",
                "tunnel.restart",
                cost="restart",
                latency_ms=(obs.now() - started) * 1000,
                server=self.ctx.active_server,
            )
            await events.put(VpnEvent(type=EventType.BOOTSTRAP_DONE))
        else:
            self.ctx.last_error = "Tunnel restart produced no traffic"
            obs.emit(
                "L1",
                "fail",
                "tunnel.restart",
                cost="restart",
                latency_ms=(obs.now() - started) * 1000,
                error_class="verify_failed",
                server=self.ctx.active_server,
            )
            await events.put(VpnEvent(type=EventType.TIMEOUT))

    async def _on_timeout(self) -> None:
        await asyncio.sleep(RECOVERY_TIMEOUT)
        await self.machine.post(VpnEvent(type=EventType.TIMEOUT))
