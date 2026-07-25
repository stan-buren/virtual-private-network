"""Telegram notification sender with IPv4-forced delivery."""

from __future__ import annotations

import logging
import os
import socket
import time
import urllib.parse
import urllib.request

logger = logging.getLogger("vpn")


class TelegramNotifier:
    """Sends alert notifications via Telegram Bot API.

    Forces IPv4 for the HTTP connection because IPv6 is disabled on the WAN
    interface by the firewall configuration. The bypass routing rule at priority 2
    routes the IPv4 Telegram IP through table main (ISP gateway).
    """

    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self._token = token or os.environ.get("VPN_TELEGRAM_TOKEN", "")
        self._chat_id = chat_id or os.environ.get("VPN_TELEGRAM_CHAT_ID", "")
        self._api_url = "https://api.telegram.org/bot%s/sendMessage" % self._token

    def send(self, message: str, retries: int = 3, retry_delay: int = 5) -> None:
        """Send a notification message via Telegram.

        Args:
            message: The message text to send.
            retries: Number of delivery retry attempts.
            retry_delay: Seconds between retry attempts.
        """
        if not self._token or not self._chat_id:
            logger.warning("Telegram token or chat_id not configured, skipping notification")
            return

        params = {
            "chat_id": self._chat_id,
            "text": "Service Alert (Asus VPN): %s" % message,
        }
        data = urllib.parse.urlencode(params).encode()

        orig_getaddrinfo = socket.getaddrinfo

        def ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
            return [
                r
                for r in orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
            ]

        for attempt in range(1, retries + 1):
            try:
                logger.debug("Telegram attempt %d/%d", attempt, retries)
                socket.getaddrinfo = ipv4_only
                urllib.request.urlopen(self._api_url, data=data, timeout=8)
                logger.info("Telegram notification sent on attempt %d", attempt)
                return
            except Exception as e:
                logger.warning("Telegram attempt %d failed: %s", attempt, e)
                if attempt < retries:
                    time.sleep(retry_delay)
            finally:
                socket.getaddrinfo = orig_getaddrinfo

        logger.error("Telegram notification failed after %d attempts", retries)

    def format_event(self, template: str, **kwargs) -> str:
        """Format a notification template with values.

        Args:
            template: Template string with {key} placeholders.
            **kwargs: Values to substitute.

        Returns:
            Formatted string.
        """
        return template.format(**kwargs)
