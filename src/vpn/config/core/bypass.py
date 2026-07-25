"""Bypass list configuration — domains/subnets to route around the VPN tunnel."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class BypassConfig:
    """Immutable bypass list configuration.

    Attributes:
        domains: Domain names whose resolved IPs bypass the VPN.
        subnets: CIDR subnets that bypass the VPN directly.
    """

    domains: list[str]
    subnets: list[str]

    @classmethod
    def _from_yaml(cls) -> BypassConfig:
        """Loads and parses the bypass list from bypass.yaml."""
        from vpn.config.paths import CONFIG_DIR

        with (CONFIG_DIR / "bypass.yaml").open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        b = data["bypass"]
        return cls(domains=b["domains"], subnets=b["subnets"])
