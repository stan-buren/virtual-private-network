"""Failed state — unrecoverable error, container will restart via Docker."""

from __future__ import annotations

import logging
import sys

from vpn.core.events import VpnEvent
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")


class FailedState(VpnState):
    """Terminal state: all recovery attempts exhausted.

    Sends final Telegram alert with last_error, then exits with code 1.
    Docker --restart=unless-stopped will restart the container.
    """

    async def on_enter(self) -> None:
        logger.critical(
            "Entering FAILED state — last error: %s",
            self.ctx.last_error or "unknown",
        )
        # The orchestrator sends the Telegram notification before sys.exit
        logger.info("Shutting down. Container will restart via Docker policy.")
        sys.exit(1)

    async def on_exit(self) -> None:
        pass

    async def handle(self, event: VpnEvent) -> None:
        pass  # Terminal state — no transitions
