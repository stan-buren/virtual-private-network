"""Restarting state — attempt to recover from failures by restarting processes."""

from __future__ import annotations

import asyncio
import logging

from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")

RESTART_TIMEOUT = 30  # seconds — covers the sing-box SOCKS port wait
MAX_RECOVERY_ATTEMPTS = 5


class RestartingState(VpnState):
    """Recovery state: replace sing-box and tun2socks, then verify the tunnel.

    Transitions to HEALTHY once the orchestrator reports a live tunnel, and to
    FAILED on timeout or once the recovery budget is exhausted.
    """

    _timeout_task: asyncio.Task[None] | None = None

    async def on_enter(self) -> None:
        self.ctx.recovery_count += 1
        if self.ctx.recovery_count > MAX_RECOVERY_ATTEMPTS:
            self.ctx.last_error = "Recovery budget exhausted after %d attempts" % MAX_RECOVERY_ATTEMPTS
            logger.error(self.ctx.last_error)
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
            return
        logger.info(
            "Entering RESTARTING state — recovery attempt #%d",
            self.ctx.recovery_count,
        )
        self._timeout_task = asyncio.create_task(self._on_timeout())
        asyncio.create_task(self._restart_tunnel())

    async def on_exit(self) -> None:
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None

    async def handle(self, event: VpnEvent) -> None:
        if event.type == EventType.BOOTSTRAP_DONE:
            logger.info("Recovery successful, returning to HEALTHY")
            await self.transition_to(
                __import__("vpn.core.state_machine.states.healthy", fromlist=["HealthyState"]).HealthyState
            )
        elif event.type == EventType.TIMEOUT:
            self.ctx.last_error = "Restart timed out after %ds" % RESTART_TIMEOUT
            logger.error(self.ctx.last_error)
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
        elif event.type == EventType.SHUTDOWN_REQUESTED:
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
        elif event.type in (EventType.TUNNEL_DIED, EventType.SINGBOX_DIED):
            self.ctx.last_error = "Process died again during recovery (%s)" % event.type.name
            logger.error(self.ctx.last_error)
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )

    async def _restart_tunnel(self) -> None:
        """Run tunnel recovery in the background and report its outcome.

        The orchestrator performs the restart; this state translates the result
        into the event the recovery loop is waiting for.
        """
        orchestrator = getattr(self.machine, "_orchestrator", None)
        events = self.machine._event_queue
        if orchestrator is None:
            self.ctx.last_error = "No orchestrator available for recovery"
            logger.error(self.ctx.last_error)
            await events.put(VpnEvent(type=EventType.TIMEOUT))
            return
        try:
            await orchestrator.restart_tunnel(self.ctx)
        except Exception:
            logger.exception("Tunnel restart failed")
            await events.put(VpnEvent(type=EventType.TIMEOUT))
        else:
            await events.put(VpnEvent(type=EventType.BOOTSTRAP_DONE))

    async def _on_timeout(self) -> None:
        await asyncio.sleep(RESTART_TIMEOUT)
        await self.machine.post(VpnEvent(type=EventType.TIMEOUT))
