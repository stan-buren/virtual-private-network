"""Server registry configuration dataclass — maps CLI names to provider outbound tags."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class ServerEntry:
    """A single VPN server entry.

    Attributes:
        tag: Provider-specific outbound tag in the profile JSON.
        country: ISO 3166-1 alpha-2 country code.
    """

    tag: str
    country: str


@dataclass(frozen=True)
class ServersConfig:
    """Immutable server registry mapping CLI names to provider outbounds.

    Attributes:
        servers: Mapping of short CLI name to ServerEntry.
    """

    servers: dict[str, ServerEntry]

    @classmethod
    def _from_yaml(cls) -> ServersConfig:
        """Loads and parses the server registry from servers.yaml."""
        from vpn.config.paths import CONFIG_DIR

        with (CONFIG_DIR / "servers.yaml").open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        servers = {}
        for name, entry in data["servers"].items():
            servers[name] = ServerEntry(tag=entry["tag"], country=entry["country"])
        return cls(servers=servers)
