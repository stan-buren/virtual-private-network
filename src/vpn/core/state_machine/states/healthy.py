"""Healthy state — normal operation, periodic health checks, waiting for failures."""

from __future__ import annotations

import asyncio
import logging

from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")


class HealthyState(VpnState):
    """Normal operating state. Health checker runs periodically.

    Transitions to DEGRADED on HEALTH_FAIL, or handles external events
    (server change, restart request, shutdown).
    """

    async def on_enter(self) -> None:
        logger.info("Entering HEALTHY state — VPN tunnel operational")
        self.ctx.fail_streak = 0
        notifier = self.machine._notifier
        if notifier:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                notifier.send,
                "VPN daemon started. Server: %s, Gateway: %s" % (
                    self.ctx.active_server or "unknown",
                    self.ctx.gateway or "unknown",
                ),
            )

    async def on_exit(self) -> None:
        pass

    async def handle(self, event: VpnEvent) -> None:
        if event.type == EventType.HEALTH_FAIL:
            self.ctx.fail_streak += 1
            logger.warning(
                "Health check failed (%d consecutive)", self.ctx.fail_streak
            )
            await self.transition_to(
                __import__("vpn.core.state_machine.states.degraded", fromlist=["DegradedState"]).DegradedState
            )
        elif event.type == EventType.SHUTDOWN_REQUESTED:
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
        elif event.type == EventType.SERVER_CHANGE_REQUESTED:
            self.ctx.target_server = event.payload.get("server_name")
            logger.info("Server change requested: %s", self.ctx.target_server)
            await self.transition_to(
                __import__("vpn.core.state_machine.states.bootstrapping", fromlist=["BootstrappingState"]).BootstrappingState
            )
        elif event.type == EventType.RESTART_REQUESTED:
            logger.info("Manual restart requested")
            await self.transition_to(
                __import__("vpn.core.state_machine.states.restarting", fromlist=["RestartingState"]).RestartingState
            )
        elif event.type == EventType.TUNNEL_DIED:
            logger.error("tun2socks died unexpectedly in HEALTHY state")
            await self.transition_to(
                __import__("vpn.core.state_machine.states.restarting", fromlist=["RestartingState"]).RestartingState
            )
