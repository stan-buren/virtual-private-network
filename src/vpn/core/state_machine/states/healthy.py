"""Healthy state — steady state. No periodic probes, no automatic actions.

The daemon bootstraps once and stays out of the way. It reacts only to real
events: an operator command, a shutdown request, or a child process that
actually exited.
"""

from __future__ import annotations

import logging

from vpn.core import obs
from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")


class HealthyState(VpnState):
    """Normal operating state: the tunnel is up and nothing is being changed."""

    async def on_enter(self) -> None:
        self.ctx.fail_streak = 0
        self.ctx.recovery_count = 0
        self.ctx.last_error = None
        obs.emit(
            "L0",
            "ok",
            "none",
            server=self.ctx.active_server,
            gateway=self.ctx.gateway,
            interface=self.ctx.interface,
            state="healthy",
        )

    async def on_exit(self) -> None:
        pass

    async def handle(self, event: VpnEvent) -> None:
        if event.type == EventType.SHUTDOWN_REQUESTED:
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
        elif event.type == EventType.SERVER_CHANGE_REQUESTED:
            self.ctx.target_server = event.payload.get("server_name")
            obs.emit(
                "CLI",
                "info",
                "server.change",
                server=self.ctx.target_server,
                cost="restart",
            )
            await self.transition_to(
                __import__("vpn.core.state_machine.states.bootstrapping", fromlist=["BootstrappingState"]).BootstrappingState
            )
        elif event.type == EventType.RESTART_REQUESTED:
            obs.emit("CLI", "info", "tunnel.restart", cost="restart")
            await self.transition_to(
                __import__("vpn.core.state_machine.states.restarting", fromlist=["RestartingState"]).RestartingState
            )
        elif event.type in (EventType.TUNNEL_DIED, EventType.SINGBOX_DIED):
            obs.emit(
                "L0",
                "fail",
                "container.restart",
                cost="disruptive",
                error_class="process_exited",
                process=event.type.name,
                pid=event.payload.get("pid"),
            )
            await self.transition_to(
                __import__("vpn.core.state_machine.states.failed", fromlist=["FailedState"]).FailedState
            )
