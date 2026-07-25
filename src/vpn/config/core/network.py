"""Network topology and routing configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class NetworkConfig:
    """Immutable network configuration.

    Attributes:
        tun_address: IP address and subnet for the tun0 virtual interface.
        tun_mtu: MTU for tun0 interface.
        mss_clamp: TCP MSS clamping value for mangle FORWARD rules.
        dns_servers: DNS server IPs to bypass through table main.
        lan_subnets: Local area network subnets to bypass VPN.
        bypass_priority_server_ips: ip rule priority for VLESS server IP bypass.
        bypass_priority_dns_start: Start of DNS bypass priority range.
        bypass_priority_dns_end: End of DNS bypass priority range.
        bypass_priority_lan_start: Start of LAN bypass priority range.
        bypass_priority_lan_end: End of LAN bypass priority range.
        bypass_priority_torrent: Priority for torrent client bypass (fwmark 1).
        bypass_priority_catchall: Priority for catch-all route into tun0.
    """

    tun_address: str
    tun_mtu: int
    mss_clamp: int
    dns_servers: list[str]
    lan_subnets: list[str]
    bypass_priority_server_ips: int
    bypass_priority_dns_start: int
    bypass_priority_dns_end: int
    bypass_priority_lan_start: int
    bypass_priority_lan_end: int
    bypass_priority_torrent: int
    bypass_priority_catchall: int

    @classmethod
    def _from_yaml(cls) -> NetworkConfig:
        """Loads and parses the network configuration from network.yaml."""
        from vpn.config.paths import CONFIG_DIR

        with (CONFIG_DIR / "network.yaml").open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        net = data["network"]
        bp = net["bypass_priorities"]
        return cls(
            tun_address=net["tun"]["address"],
            tun_mtu=net["tun"]["mtu"],
            mss_clamp=net["mss_clamp"],
            dns_servers=net["dns_servers"],
            lan_subnets=net["lan_subnets"],
            bypass_priority_server_ips=bp["server_ips"],
            bypass_priority_dns_start=bp["dns_start"],
            bypass_priority_dns_end=bp["dns_end"],
            bypass_priority_lan_start=bp["lan_start"],
            bypass_priority_lan_end=bp["lan_end"],
            bypass_priority_torrent=bp["torrent"],
            bypass_priority_catchall=bp["catchall"],
        )
