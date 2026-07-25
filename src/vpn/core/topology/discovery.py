"""Network topology discovery — gateway, interface, server IPs, DNS resolution."""

from __future__ import annotations

import logging
import re
import socket
from dataclasses import dataclass

from vpn.core.ports import FilesystemPort, ShellPort
from vpn.logger.exceptions import VpnConnectionError

logger = logging.getLogger("vpn")

DOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9.-]+$")
IPV4_REGEX = re.compile(r"^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$")


@dataclass(frozen=True)
class Topology:
    """Discovered network topology information.

    Attributes:
        gateway: Default IPv4 gateway address.
        interface: Physical network interface name.
    """

    gateway: str
    interface: str


class TopologyDiscovery:
    """Discovers the system's default gateway and physical network interface."""

    def __init__(self, shell: ShellPort, max_retries: int = 15, retry_delay: int = 2):
        self._shell = shell
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    def discover(self) -> Topology:
        """Discover default gateway and interface via 'ip route'.

        Returns:
            Topology: The discovered gateway and interface.

        Raises:
            VpnConnectionError: If discovery fails after max_retries.
        """
        for attempt in range(1, self._max_retries + 1):
            logger.debug("Topology discovery attempt %d/%d", attempt, self._max_retries)
            result = self._shell.run("ip -4 route show default", capture=True)
            if result and result.stdout:
                match = re.search(r"via (\S+) dev (\S+)", result.stdout)
                if match:
                    topology = Topology(gateway=match.group(1), interface=match.group(2))
                    logger.info(
                        "Topology discovered: interface=%s, gateway=%s",
                        topology.interface,
                        topology.gateway,
                    )
                    return topology
            if attempt < self._max_retries:
                import time
                time.sleep(self._retry_delay)
        raise VpnConnectionError(
            "Topology discovery failed after %d attempts" % self._max_retries
        )


class DnsResolver:
    """Resolves hostnames to IPv4 addresses."""

    @staticmethod
    def available(test_host: str = "8.8.8.8", test_port: int = 53, timeout: float = 3.0) -> bool:
        """Quick check: can we reach a DNS server on port 53?

        Args:
            test_host: DNS server IP to test.
            test_port: Port number (53 for DNS).
            timeout: Connection timeout in seconds.

        Returns:
            True if the DNS server is reachable.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((test_host, test_port))
            sock.close()
            return True
        except Exception:
            return False

    def resolve_ipv4(self, hostname: str, shell: ShellPort | None = None) -> list[str]:
        """Resolve a hostname to a list of unique IPv4 addresses.

        Args:
            hostname: The hostname to resolve.
            shell: Optional shell adapter for getent fallback.

        Returns:
            List of unique IPv4 address strings. Empty if resolution failed.
        """
        if not DOMAIN_REGEX.match(hostname):
            logger.warning("Invalid hostname characters: %s", hostname)
            return []

        ips: set[str] = set()
        try:
            addr_info = socket.getaddrinfo(hostname, None, socket.AF_INET)
            for info in addr_info:
                ip = info[4][0]
                if ip:
                    ips.add(ip)
        except Exception as e:
            logger.debug("getaddrinfo failed for %s: %s", hostname, e)
            if shell:
                result = shell.run("getent ahosts %s" % hostname, capture=True)
                if result and result.stdout:
                    for line in result.stdout.splitlines():
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == "STREAM":
                            candidate = parts[0]
                            if "." in candidate and ":" not in candidate:
                                ips.add(candidate)
        return list(ips)


class ServerIpResolver:
    """Extracts remote VPN server IPs from sing-box configuration to prevent routing loops."""

    def __init__(self, fs: FilesystemPort, dns: DnsResolver):
        self._fs = fs
        self._dns = dns

    def resolve_all(self, profile_path: str, shell: ShellPort) -> set[str]:
        """Scan sing-box config outbounds and resolve all remote server IPs.

        Args:
            profile_path: Path to sing-box config JSON.
            shell: Shell adapter for fallback resolution.

        Returns:
            Set of unique IPv4 server addresses.
        """
        server_ips: set[str] = set()
        if not self._fs.exists(profile_path):
            logger.warning("Profile config not found at %s", profile_path)
            return server_ips

        try:
            data = self._fs.read_json(profile_path)
            outbounds = data.get("outbounds", [])
            logger.debug("Scanning %d outbounds for server IPs", len(outbounds))

            for outbound in outbounds:
                server = outbound.get("server", "")
                if not server or server.startswith("127.") or server.startswith("::") or server == "localhost":
                    continue

                try:
                    socket.inet_aton(server)
                    server_ips.add(server)
                    logger.info("Found server IP: %s", server)
                except socket.error:
                    resolved = self._dns.resolve_ipv4(server, shell)
                    for ip in resolved:
                        server_ips.add(ip)
                        logger.info("Resolved server %s to IP: %s", server, ip)
        except Exception:
            logger.exception("Failed to scan profile for server IPs")
        return server_ips
