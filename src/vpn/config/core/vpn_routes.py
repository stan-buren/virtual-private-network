"""VPN routes configuration — domains/subnets to force through the VPN tunnel."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class VpnRoutesConfig:
    """Immutable VPN-forced routes configuration.

    Attributes:
        domains: Domain names forced through the VPN tunnel.
        wildcards: Wildcard domain patterns (e.g. 'audiobookbay.*').
        subnets: CIDR subnets forced through the VPN tunnel.
    """

    domains: list[str]
    wildcards: list[str]
    subnets: list[str]

    @classmethod
    def _from_yaml(cls) -> VpnRoutesConfig:
        """Loads and parses the VPN routes from vpn-routes.yaml."""
        from vpn.config.paths import CONFIG_DIR

        with (CONFIG_DIR / "vpn-routes.yaml").open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        vr = data["vpn_routes"]
        return cls(
            domains=vr["domains"], wildcards=vr["wildcards"], subnets=vr["subnets"]
        )
