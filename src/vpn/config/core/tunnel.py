"""Tunnel and proxy configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class TunnelConfig:
    """Immutable tunnel configuration.

    Attributes:
        socks5_host: SOCKS5 proxy host (usually 127.0.0.1).
        socks5_port: SOCKS5 proxy port (sing-box default: 3066).
        mac_proxy_enabled: Whether to use MacBook SSH SOCKS5 proxy.
        mac_proxy_ip: MacBook IP address for SSH tunnel.
        mac_proxy_user: SSH username for MacBook connection.
        mac_proxy_port: Local SOCKS5 port for MacBook SSH tunnel.
    """

    socks5_host: str
    socks5_port: int
    mac_proxy_enabled: bool
    mac_proxy_ip: str
    mac_proxy_user: str
    mac_proxy_port: int

    @classmethod
    def _from_yaml(cls) -> TunnelConfig:
        """Loads and parses the tunnel configuration from tunnel.yaml."""
        from vpn.config.paths import CONFIG_DIR

        with (CONFIG_DIR / "tunnel.yaml").open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        t = data["tunnel"]
        mac = t["mac_proxy"]
        return cls(
            socks5_host=t["socks5"]["host"],
            socks5_port=t["socks5"]["port"],
            mac_proxy_enabled=mac["enabled"],
            mac_proxy_ip=mac["ip"],
            mac_proxy_user=mac["user"],
            mac_proxy_port=mac["port"],
        )
