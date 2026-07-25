"""HTTP adapter — sends HTTP requests via urllib."""

from __future__ import annotations

import logging
import urllib.request

from vpn.core.ports import HttpPort

logger = logging.getLogger("vpn")


class UrllibHttpAdapter:
    """Implements HttpPort using urllib.request.urlopen."""

    def post(self, url: str, data: bytes, timeout: int) -> None:
        logger.debug("POST %s", url)
        urllib.request.urlopen(url, data=data, timeout=timeout)
