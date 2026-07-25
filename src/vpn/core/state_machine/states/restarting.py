"""Restarting state — attempt to recover from failures by restarting processes."""

from __future__ import annotations

import asyncio
import logging

from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")

RESTART_TIMEOUT = 10  # seconds


class RestartingState(VpnState):
    """Recovery state: restart sing-box, wait for port, restart tun2socks.

    Transitions to HEALTHY on success, FAILED on timeout or persistent failure.
    """

    _timeout_task: asyncio.Task | None = None

    async def on_enter(self) -> None:
        self.ctx.recovery_count += 1
        logger.info(
            "Entering RESTARTING state — recovery attempt #%d",
            self.ctx.recovery_count,
        )
        self._timeout_task = asyncio.create_task(self._on_timeout())
        # The orchestrator handles the actual restart logic.
        # We wait for BOOTSTRAP_DONE after restart.

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
        elif event.type == EventType.TUNNEL_DIED:
            self.ctx.last_error = "tun2socks died repeatedly during recovery"
            logger.error(self.ctx.last_error)
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )

    async def _on_timeout(self) -> None:
        await asyncio.sleep(RESTART_TIMEOUT)
        await self.machine.post(VpnEvent(type=EventType.TIMEOUT))
