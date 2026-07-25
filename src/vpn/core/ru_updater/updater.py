"""RU subnet cache updater — fetches IPv4 subnets daily as a background task."""

from __future__ import annotations

import asyncio
import logging
import urllib.request
import os

from vpn.core.ports import FilesystemPort

logger = logging.getLogger("vpn")

RU_LIST_URL = (
    "https://raw.githubusercontent.com/ipverse/country-ip-blocks/"
    "master/country/ru/ipv4-aggregated.txt"
)


class RuSubnetUpdater:
    """Fetches the latest Russian IPv4 subnet list for VPN bypass routing.

    Runs as a background asyncio task: fetches immediately on startup,
    then every 24 hours thereafter. No systemd timer, no cron — fully autonomous.
    """

    def __init__(self, fs: FilesystemPort, cache_path: str):
        self._fs = fs
        self._cache_path = cache_path

    async def run_forever(self) -> None:
        """Fetch immediately, then every 24 hours."""
        logger.info("RU subnet updater started — cache path: %s", self._cache_path)
        while True:
            await self._fetch()
            logger.debug("Next RU subnet update in 24 hours")
            await asyncio.sleep(86400)

    async def fetch_once(self) -> int:
        """Fetch once and return the number of subnets cached.

        Returns:
            Number of subnet lines written to cache.
        """
        return await self._fetch()

    async def _fetch(self) -> int:
        """Fetch the RU subnet list and write to cache.

        Returns:
            Number of subnets cached, or 0 on failure.
        """
        try:
            logger.info("Fetching RU subnets from %s", RU_LIST_URL)
            response = urllib.request.urlopen(RU_LIST_URL, timeout=30)
            data = response.read().decode("utf-8")
            self._fs.makedirs(os.path.dirname(self._cache_path))
            self._fs.write_text(self._cache_path, data)
            count = len(data.splitlines())
            logger.info("Cached %d RU subnets to %s", count, self._cache_path)
            return count
        except Exception:
            logger.exception("RU subnet update failed")
            return 0
