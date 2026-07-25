"""Tests for topology discovery and DNS resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from vpn.core.topology.discovery import DnsResolver, ServerIpResolver, Topology, TopologyDiscovery


class TestTopology:
    def test_frozen_dataclass(self) -> None:
        t = Topology(gateway="10.0.0.1", interface="eth0")
        assert t.gateway == "10.0.0.1"
        assert t.interface == "eth0"


class TestTopologyDiscovery:
    def test_parses_ip_route_output(self) -> None:
        mock_shell = MagicMock()
        mock_result = MagicMock()
        mock_result.stdout = "default via 192.168.1.1 dev eth0"
        mock_result.returncode = 0
        mock_shell.run.return_value = mock_result

        discovery = TopologyDiscovery(mock_shell, max_retries=1, retry_delay=0)
        result = discovery.discover()
        assert result.gateway == "192.168.1.1"
        assert result.interface == "eth0"


class TestDnsResolver:
    def test_resolve_ipv4_returns_list(self) -> None:
        resolver = DnsResolver()
        ips = resolver.resolve_ipv4("google.com")
        assert isinstance(ips, list)

    def test_invalid_hostname_returns_empty(self) -> None:
        resolver = DnsResolver()
        ips = resolver.resolve_ipv4("!!!invalid!!!")
        assert ips == []

    def test_available_returns_bool(self) -> None:
        resolver = DnsResolver()
        result = resolver.available()
        assert isinstance(result, bool)
