"""Telegram notification configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class NotificationConfig:
    """Immutable notification configuration.

    Attributes:
        retries: Number of delivery retry attempts.
        retry_delay: Seconds between retry attempts.
        timeout: HTTP request timeout in seconds.
        events: Mapping of event name to message template string.
    """

    retries: int
    retry_delay: int
    timeout: int
    events: dict[str, str]

    @classmethod
    def _from_yaml(cls) -> NotificationConfig:
        """Loads and parses the notification configuration from notification.yaml."""
        from vpn.config.paths import CONFIG_DIR

        with (CONFIG_DIR / "notification.yaml").open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        n = data["notification"]
        return cls(
            retries=n["retries"],
            retry_delay=n["retry_delay"],
            timeout=n["timeout"],
            events=n["events"],
        )
