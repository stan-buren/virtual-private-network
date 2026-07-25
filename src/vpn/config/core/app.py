"""Application-level configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class AppConfig:
    """Immutable application-level configuration.

    Attributes:
        tag: Syslog identifier tag for the daemon.
        table_id: Linux routing table ID for VPN routes.
        chain_name: iptables chain name for NAT rules.
        provider: Name of the VPN provider adapter to use (e.g. 'akonit').
        sing_box_service: Name of the sing-box systemd service or process.
        unbound_service: Name of the unbound DNS resolver service.
    """

    tag: str
    table_id: str
    chain_name: str
    provider: str
    sing_box_service: str
    unbound_service: str

    @classmethod
    def _from_yaml(cls) -> AppConfig:
        """Loads and parses the application configuration from app.yaml.

        Returns:
            AppConfig: A type-safe configuration object.

        Raises:
            FileNotFoundError: If app.yaml is missing.
            yaml.YAMLError: If app.yaml contains invalid syntax.
        """
        from vpn.config.paths import CONFIG_DIR

        with (CONFIG_DIR / "app.yaml").open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        app = data["app"]
        return cls(
            tag=app["tag"],
            table_id=app["table_id"],
            chain_name=app["chain_name"],
            provider=app["provider"],
            sing_box_service=app["sing_box_service"],
            unbound_service=app["unbound_service"],
        )
