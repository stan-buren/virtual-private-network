"""Restarting state — attempt to recover from failures by restarting processes."""

from __future__ import annotations

import asyncio
import logging

from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")

RECOVERY_TIMEOUT = 240  # seconds — restart, rotation and subscription refresh
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
            self.ctx.last_error = "Recovery timed out after %ds" % RECOVERY_TIMEOUT
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
        """Run the recovery ladder and report its real outcome.

        Restarting the same broken config is only the first rung: when the
        selected provider endpoint is dead the processes come back and the
        host stays blackholed. Every rung is therefore verified through the
        SOCKS inbound, and the ladder escalates — restart, rotate to a
        reachable node, refresh the subscription, rotate again. A
        "Recovery successful" line can no longer be printed for a tunnel that
        does not carry traffic.
        """
        orchestrator = getattr(self.machine, "_orchestrator", None)
        events = self.machine._event_queue
        if orchestrator is None:
            self.ctx.last_error = "No orchestrator available for recovery"
            logger.error(self.ctx.last_error)
            await events.put(VpnEvent(type=EventType.TIMEOUT))
            return

        ok = await self._rung("restart", orchestrator.restart_and_verify)
        if not ok:
            ok = await self._rung("rotate", orchestrator.rotate_and_restart)
        if not ok:
            ok = await self._rung("config update", orchestrator.refresh_and_restart)
        if not ok:
            ok = await self._rung("rotate after update", orchestrator.rotate_and_restart)

        if ok:
            await events.put(VpnEvent(type=EventType.BOOTSTRAP_DONE))
        else:
            self.ctx.last_error = "All recovery rungs failed — no node carries traffic"
            logger.error(self.ctx.last_error)
            await events.put(VpnEvent(type=EventType.TIMEOUT))

    async def _rung(self, name: str, action) -> bool:
        """Run one recovery rung and report whether it produced a live tunnel."""
        logger.info("Recovery rung: %s", name)
        try:
            ok = bool(await action(self.ctx))
        except Exception:
            logger.exception("Recovery rung %r crashed", name)
            return False
        if ok:
            logger.info("Recovery rung %r verified — tunnel carries traffic", name)
        else:
            logger.warning("Recovery rung %r did not produce a working tunnel", name)
        return ok

    async def _on_timeout(self) -> None:
        await asyncio.sleep(RECOVERY_TIMEOUT)
        await self.machine.post(VpnEvent(type=EventType.TIMEOUT))
