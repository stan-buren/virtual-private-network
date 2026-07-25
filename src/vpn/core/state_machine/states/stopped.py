"""Stopped state — VPN disabled, traffic goes direct."""

from __future__ import annotations

import logging

from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")


class StoppedState(VpnState):
    """VPN is stopped: no tunnel, no routing, no firewall rules.

    All traffic flows directly through the physical interface.
    Only RESTART_REQUESTED transitions back to BootstrappingState.
    """

    async def on_enter(self) -> None:
        logger.info("Entering STOPPED state — VPN disabled, traffic direct")

    async def on_exit(self) -> None:
        pass

    async def handle(self, event: VpnEvent) -> None:
        if event.type in (EventType.RESTART_REQUESTED,):
            from vpn.core.state_machine.states.bootstrapping import BootstrappingState
            await self.machine.transition_to(BootstrappingState)
