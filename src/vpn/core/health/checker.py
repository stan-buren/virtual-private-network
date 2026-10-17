"""Tunnel health checker — verifies traffic really leaves through sing-box."""

from __future__ import annotations

import asyncio
import logging
import random

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")


class HealthChecker:
    """Periodically verifies that the tunnel carries traffic.

    Probes deliberately go through the local SOCKS inbound instead of relying
    on host routing: when `tun0` is DOWN the kernel silently falls back to the
    physical uplink, so a plain `curl` reports "internet OK" while nothing is
    tunnelled at all. A SOCKS probe cannot be bypassed that way, and the extra
    `tun0` check catches a device that still has a route but no carrier.

    Any HTTP status counts as success: a 403/404 still proves the request
    travelled through sing-box and reached the far side.
    """

    def __init__(
        self,
        shell: ShellPort,
        targets: list[str],
        user_agents: list[str],
        interval_range: tuple[int, int] = (20, 35),
        curl_timeout: int = 6,
        sample_size: int = 2,
        socks_host: str = "127.0.0.1",
        socks_port: int = 3066,
        tun_device: str = "tun0",
    ):
        self._shell = shell
        self._targets = targets
        self._user_agents = user_agents
        self._interval_min, self._interval_max = interval_range
        self._curl_timeout = curl_timeout
        self._sample_size = sample_size
        self._socks_host = socks_host
        self._socks_port = socks_port
        self._tun_device = tun_device

    async def run_forever(self, event_queue: asyncio.Queue) -> None:
        """Run periodic health checks, posting results as events.

        Args:
            event_queue: The asyncio event queue to post HEALTH_OK/HEALTH_FAIL.
        """
        from vpn.core.events import EventType, VpnEvent

        while True:
            delay = random.randint(self._interval_min, self._interval_max)
            await asyncio.sleep(delay)

            # _check() shells out to curl synchronously; run it in a thread
            # so a slow probe never stalls the state machine's event loop.
            ok = await asyncio.get_running_loop().run_in_executor(None, self._check)
            event = VpnEvent(
                type=EventType.HEALTH_OK if ok else EventType.HEALTH_FAIL,
                payload={"target": getattr(self, "_last_target", "unknown")},
            )
            logger.debug("Health check result: %s", "OK" if ok else "FAIL")
            await event_queue.put(event)

    def _tun_up(self) -> bool:
        """Return True when the tunnel device exists and is administratively up."""
        result = self._shell.run(
            "ip -br link show %s 2>/dev/null" % self._tun_device, capture=True
        )
        fields = (result.stdout or "").split() if result is not None else []
        return len(fields) >= 2 and fields[1] == "UP"

    def _probe(self, endpoint: str, user_agent: str) -> bool:
        """Fetch *endpoint* through the SOCKS inbound and accept any HTTP status."""
        command = (
            "curl -s -o /dev/null -w '%%{http_code}' --max-time %d "
            "--socks5-hostname %s:%d -A '%s' %s"
            % (
                self._curl_timeout,
                self._socks_host,
                self._socks_port,
                user_agent,
                endpoint,
            )
        )
        result = self._shell.run(
            command, capture=True, timeout=self._curl_timeout + 2
        )
        code = (result.stdout or "").strip() if result is not None else ""
        if result is None or result.returncode != 0:
            return False
        return code.isdigit() and len(code) == 3 and code != "000"

    def _check(self) -> bool:
        """Run a connectivity check through the tunnel.

        Returns:
            True if the device is up and any target answers through SOCKS.
        """
        if not self._tun_up():
            logger.debug("Health check: %s is not UP", self._tun_device)
            return False

        targets = random.sample(
            self._targets, min(self._sample_size, len(self._targets))
        )
        for endpoint in targets:
            user_agent = random.choice(self._user_agents)
            self._last_target = endpoint
            logger.debug(
                "Health check: %s (via SOCKS %s:%d)",
                endpoint,
                self._socks_host,
                self._socks_port,
            )
            if self._probe(endpoint, user_agent):
                logger.debug("Health check OK: %s", endpoint)
                return True
            logger.debug("Health check unreachable: %s", endpoint)
        return False
