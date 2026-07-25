"""Bypass list loader — combines RU cache, custom bypass, and forced VPN routes."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vpn.core.ports import FilesystemPort, ShellPort
from vpn.core.routing.route_table import RouteEntry
from vpn.core.topology.discovery import DnsResolver, IPV4_REGEX

logger = logging.getLogger("vpn")

COMMON_TLDS = ["lu", "is", "fi", "nl", "me", "shop", "cc", "to", "li", "se", "ch"]


@dataclass(frozen=True)
class BypassDomain:
    """A domain entry to be resolved for bypass/VPN routing.

    Attributes:
        domain: The domain name.
        is_wildcard: Whether this is a wildcard pattern (e.g. 'audiobookbay.*').
        force_vpn: If True, route through VPN; if False, bypass VPN.
    """

    domain: str
    is_wildcard: bool = False
    force_vpn: bool = False


class BypassLoader:
    """Loads and resolves routes from RU subnets, bypass list, and VPN-forced list.

    Generates RouteEntry objects for batch injection into the routing table.
    """

    def __init__(
        self,
        shell: ShellPort,
        fs: FilesystemPort,
        dns: DnsResolver,
    ):
        self._shell = shell
        self._fs = fs
        self._dns = dns

    def load_all(
        self,
        ru_cache_path: str,
        bypass_domains: list[str],
        bypass_subnets: list[str],
        vpn_domains: list[str],
        vpn_wildcards: list[str],
        vpn_subnets: list[str],
        gateway: str,
        interface: str,
        table_id: str,
    ) -> list[RouteEntry]:
        """Load all route entries from all sources.

        Args:
            ru_cache_path: Path to the RU subnets cache file.
            bypass_domains: Domains to resolve and bypass VPN.
            bypass_subnets: CIDR subnets to bypass VPN.
            vpn_domains: Domains to force through VPN.
            vpn_wildcards: Wildcard domain patterns forced through VPN.
            vpn_subnets: CIDR subnets forced through VPN.
            gateway: Default gateway IP.
            interface: Physical interface name.
            table_id: Routing table ID.

        Returns:
            List of RouteEntry objects to apply.
        """
        entries: list[RouteEntry] = []
        added: set[str] = set()
        dns_ok = self._dns.available()

        # 1. RU subnets (bypass)
        if self._fs.exists(ru_cache_path):
            logger.info("Loading RU subnets from %s", ru_cache_path)
            content = self._fs.read_text(ru_cache_path)
            for line in content.splitlines():
                subnet = line.strip()
                if IPV4_REGEX.match(subnet) and subnet not in added:
                    entries.append(
                        RouteEntry(
                            subnet=subnet,
                            via=gateway,
                            dev=interface,
                            table_id=table_id,
                        )
                    )
                    added.add(subnet)
            logger.info("Loaded %d RU subnets", len(added))

        # 2. Custom bypass subnets
        for subnet in bypass_subnets:
            if IPV4_REGEX.match(subnet) and subnet not in added:
                entries.append(
                    RouteEntry(
                        subnet=subnet,
                        via=gateway,
                        dev=interface,
                        table_id=table_id,
                    )
                )
                added.add(subnet)

        # 3. Custom bypass domains
        for domain in bypass_domains:
            self._resolve_and_add(entries, added, domain, gateway, interface, table_id, dns_ok)

        # 4. Forced VPN subnets
        for subnet in vpn_subnets:
            if IPV4_REGEX.match(subnet) and subnet not in added:
                entries.append(
                    RouteEntry(
                        subnet=subnet,
                        via=None,
                        dev="tun0",
                        table_id=table_id,
                    )
                )
                added.add(subnet)

        # 5. Forced VPN domains
        for domain in vpn_domains:
            self._resolve_and_add(
                entries, added, domain, None, "tun0", table_id, dns_ok
            )

        # 6. Forced VPN wildcards
        for wildcard in vpn_wildcards:
            if ".*" in wildcard:
                base = wildcard.replace(".*", "")
                for tld in COMMON_TLDS:
                    self._resolve_and_add(
                        entries, added, "%s.%s" % (base, tld), None, "tun0", table_id, dns_ok
                    )

        return entries

    def _resolve_and_add(
        self,
        entries: list[RouteEntry],
        added: set[str],
        domain: str,
        via: str | None,
        dev: str,
        table_id: str,
        dns_ok: bool,
    ) -> None:
        """Resolve a domain and add /32 entries for each resolved IP."""
        if not dns_ok:
            logger.warning("DNS unavailable, skipping domain: %s", domain)
            return

        ips = self._dns.resolve_ipv4(domain, self._shell)
        for ip in ips:
            subnet = "%s/32" % ip
            if subnet not in added:
                entries.append(
                    RouteEntry(
                        subnet=subnet,
                        via=via,
                        dev=dev,
                        table_id=table_id,
                    )
                )
                added.add(subnet)
        if not ips:
            logger.warning("Could not resolve domain: %s", domain)
