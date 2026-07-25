"""Degraded state — one or more health checks failed, monitoring before recovery."""

from __future__ import annotations

import logging

from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")


class DegradedState(VpnState):
    """Degraded operating state. Health checks are failing consecutively.

    Transitions back to HEALTHY on HEALTH_OK, or to RESTARTING on threshold.
    """

    async def on_enter(self) -> None:
        logger.warning(
            "Entering DEGRADED state — fail streak: %d", self.ctx.fail_streak
        )

    async def on_exit(self) -> None:
        pass

    async def handle(self, event: VpnEvent) -> None:
        if event.type == EventType.HEALTH_OK:
            logger.info("Health restored, returning to HEALTHY")
            await self.transition_to(
                __import__("vpn.core.state_machine.states.healthy", fromlist=["HealthyState"]).HealthyState
            )
        elif event.type == EventType.HEALTH_FAIL:
            self.ctx.fail_streak += 1
            logger.warning(
                "Health check failed (%d consecutive)", self.ctx.fail_streak
            )
            if self.ctx.fail_streak >= 3:
                logger.error("Fail threshold reached, entering RESTARTING")
                await self.transition_to(
                    __import__("vpn.core.state_machine.states.restarting", fromlist=["RestartingState"]).RestartingState
                )
        elif event.type == EventType.SHUTDOWN_REQUESTED:
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
        elif event.type == EventType.TUNNEL_DIED:
            logger.error("tun2socks died in DEGRADED state")
            await self.transition_to(
                __import__("vpn.core.state_machine.states.restarting", fromlist=["RestartingState"]).RestartingState
            )
