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
        # ── Emergency network teardown BEFORE exit ──────────────────────
        # Container modifies HOST network stack (network_mode: host).
        # If we exit without cleanup, ip rules, iptables, table 100,
        # and tun0 remain on the host — breaking internet on next start.
        orch = self.machine._orchestrator
        if orch is not None:
            try:
                await orch.teardown_network()
            except Exception:
                logger.exception("Teardown during FAILED state crashed")
        logger.info("Shutting down. Container will restart via Docker policy.")
        sys.exit(1)

    async def on_exit(self) -> None:
        pass

    async def handle(self, event: VpnEvent) -> None:
        pass  # Terminal state — no transitions
