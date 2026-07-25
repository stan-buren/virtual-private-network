"""Connectivity health checker — verifies internet access via curl."""

from __future__ import annotations

import asyncio
import logging
import random

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")


class HealthChecker:
    """Periodically checks internet connectivity by probing HTTPS endpoints.

    Picks random targets and User-Agent strings to avoid pattern detection.
    Runs as an asyncio background task, posting events to the state machine queue.
    """

    def __init__(
        self,
        shell: ShellPort,
        targets: list[str],
        user_agents: list[str],
        interval_range: tuple[int, int] = (25, 55),
        curl_timeout: int = 8,
        sample_size: int = 2,
    ):
        self._shell = shell
        self._targets = targets
        self._user_agents = user_agents
        self._interval_min, self._interval_max = interval_range
        self._curl_timeout = curl_timeout
        self._sample_size = sample_size

    async def run_forever(self, event_queue: asyncio.Queue) -> None:
        """Run periodic health checks, posting results as events.

        Args:
            event_queue: The asyncio event queue to post HEALTH_OK/HEALTH_FAIL.
        """
        from vpn.core.events import EventType, VpnEvent

        while True:
            delay = random.randint(self._interval_min, self._interval_max)
            await asyncio.sleep(delay)

            ok = self._check()
            event = VpnEvent(
                type=EventType.HEALTH_OK if ok else EventType.HEALTH_FAIL,
                payload={"target": getattr(self, "_last_target", "unknown")},
            )
            logger.debug("Health check result: %s", "OK" if ok else "FAIL")
            await event_queue.put(event)

    def _check(self) -> bool:
        """Run a connectivity check against random targets.

        Returns:
            True if any target responds successfully.
        """
        targets = random.sample(self._targets, min(self._sample_size, len(self._targets)))
        for endpoint in targets:
            user_agent = random.choice(self._user_agents)
            self._last_target = endpoint
            logger.debug("Health check: %s", endpoint)
            result = self._shell.run(
                "curl -sI --max-time %d -A '%s' %s"
                % (self._curl_timeout, user_agent, endpoint),
                capture=True,
            )
            if result and result.returncode == 0:
                logger.debug("Health check OK: %s", endpoint)
                return True
            logger.debug("Health check unreachable: %s", endpoint)
        return False
