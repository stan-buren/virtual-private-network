"""Subscription configuration — where to refresh the sing-box provider profile."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class SubscriptionConfig:
    """Immutable subscription config.

    Attributes:
        url: Provider subscription URL returning a sing-box profile JSON.
    """

    url: str

    @classmethod
    def _from_yaml(cls) -> SubscriptionConfig:
        """Load the subscription URL from config/subscription.yaml.

        Returns:
            SubscriptionConfig: The parsed configuration.

        Raises:
            FileNotFoundError: If subscription.yaml is missing.
            yaml.YAMLError: If subscription.yaml is invalid.
        """
        from vpn.config.paths import CONFIG_DIR

        with (CONFIG_DIR / "subscription.yaml").open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(url=data.get("url", ""))

