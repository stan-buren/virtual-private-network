"""Bootstrapping state — initial setup before entering the HEALTHY run loop."""

from __future__ import annotations

import asyncio
import logging

from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")

BOOTSTRAP_TIMEOUT = 60  # seconds


class BootstrappingState(VpnState):
    """Initial state: deploy config, discover topology, configure network, start processes.

    Transitions to HEALTHY on success, FAILED on timeout or error.
    """

    _timeout_task: asyncio.Task | None = None

    async def on_enter(self) -> None:
        logger.info("Entering BOOTSTRAPPING state")
        self._timeout_task = asyncio.create_task(self._on_timeout())
        # Bootstrap triggered externally by __main__.py
        pass

    async def on_exit(self) -> None:
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None

    async def handle(self, event: VpnEvent) -> None:
        if event.type == EventType.BOOTSTRAP_DONE:
            logger.info("Bootstrap complete, transitioning to HEALTHY")
            await self.transition_to(
                __import__("vpn.core.state_machine.states.healthy", fromlist=["HealthyState"]).HealthyState
            )
        elif event.type == EventType.SHUTDOWN_REQUESTED:
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
        elif event.type == EventType.SINGBOX_DIED:
            logger.error("sing-box died during bootstrap — transitioning to RESTARTING")
            await self.transition_to(
                __import__("vpn.core.state_machine.states.restarting", fromlist=["RestartingState"]).RestartingState
            )
        elif event.type == EventType.TIMEOUT:
            self.ctx.last_error = "Bootstrap timed out after %ds" % BOOTSTRAP_TIMEOUT
            logger.error(self.ctx.last_error)
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
    async def _on_timeout(self) -> None:
        await asyncio.sleep(BOOTSTRAP_TIMEOUT)
        await self.machine.post(VpnEvent(type=EventType.TIMEOUT))
