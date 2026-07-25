"""Tests for bypass loader — RU cache parsing, domain resolution, wildcard expansion."""

from __future__ import annotations

from unittest.mock import MagicMock

from vpn.core.routing.bypass_loader import BypassLoader
from vpn.core.topology.discovery import DnsResolver


class TestBypassLoader:
    def test_load_all_returns_list(self) -> None:
        """Smoke test: load_all returns a list even with no data."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock()
        mock_dns.available.return_value = False

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=["example.com"],
            bypass_subnets=[],
            vpn_domains=["vpn.example.com"],
            vpn_wildcards=[],
            vpn_subnets=[],
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        assert isinstance(entries, list)

    def test_load_subnets_directly(self) -> None:
        """Bypass and VPN subnets are loaded without DNS resolution."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock()
        mock_dns.available.return_value = False

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=[],
            bypass_subnets=["1.1.1.1/32"],
            vpn_domains=[],
            vpn_wildcards=[],
            vpn_subnets=["2.2.2.2/32"],
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        assert len(entries) == 2

    def test_bypass_subnet_uses_gateway_and_interface(self) -> None:
        """Bypass subnets route through the gateway on the physical interface."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock()
        mock_dns.available.return_value = False

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=[],
            bypass_subnets=["10.10.0.0/16"],
            vpn_domains=[],
            vpn_wildcards=[],
            vpn_subnets=[],
            gateway="192.168.1.1",
            interface="eth0",
            table_id="100",
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry.subnet == "10.10.0.0/16"
        assert entry.via == "192.168.1.1"
        assert entry.dev == "eth0"
        assert entry.table_id == "100"

    def test_vpn_subnet_uses_tun0_no_gateway(self) -> None:
        """VPN subnets route through tun0 with no via gateway."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock()
        mock_dns.available.return_value = False

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=[],
            bypass_subnets=[],
            vpn_domains=[],
            vpn_wildcards=[],
            vpn_subnets=["5.5.5.0/24"],
            gateway="192.168.1.1",
            interface="eth0",
            table_id="200",
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry.subnet == "5.5.5.0/24"
        assert entry.via is None
        assert entry.dev == "tun0"
        assert entry.table_id == "200"

    def test_load_ru_cache_parses_subnets(self) -> None:
        """RU cache file lines are parsed and added as bypass entries."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.read_text.return_value = (
            "1.0.0.0/8\n"
            "2.0.0.0/8\n"
            "# comment line\n"
            "3.0.0.0/8\n"
            "invalid\n"
        )
        mock_dns = MagicMock()
        mock_dns.available.return_value = False

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache/ru.txt",
            bypass_domains=[],
            bypass_subnets=[],
            vpn_domains=[],
            vpn_wildcards=[],
            vpn_subnets=[],
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        # Three valid IPv4 subnets; "# comment" and "invalid" are skipped
        assert len(entries) == 3
        subnets = {e.subnet for e in entries}
        assert subnets == {"1.0.0.0/8", "2.0.0.0/8", "3.0.0.0/8"}
        for entry in entries:
            assert entry.via == "10.0.0.1"
            assert entry.dev == "eth0"

    def test_skips_ru_cache_when_missing(self) -> None:
        """No attempt to read RU cache if the file does not exist."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock()
        mock_dns.available.return_value = False

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/nonexistent/cache",
            bypass_domains=[],
            bypass_subnets=["1.1.1.1/32"],
            vpn_domains=[],
            vpn_wildcards=[],
            vpn_subnets=[],
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        mock_fs.read_text.assert_not_called()
        assert len(entries) == 1

    def test_resolve_bypass_domain_creates_slash32_entries(self) -> None:
        """Resolved bypass domain IPs become /32 entries through the gateway."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock(spec=DnsResolver)
        mock_dns.available.return_value = True
        mock_dns.resolve_ipv4.return_value = ["1.2.3.4", "5.6.7.8"]

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=["bypass.example.com"],
            bypass_subnets=[],
            vpn_domains=[],
            vpn_wildcards=[],
            vpn_subnets=[],
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        mock_dns.resolve_ipv4.assert_called_once_with("bypass.example.com", mock_shell)
        assert len(entries) == 2
        assert entries[0].subnet == "1.2.3.4/32"
        assert entries[0].via == "10.0.0.1"
        assert entries[0].dev == "eth0"
        assert entries[1].subnet == "5.6.7.8/32"
        assert entries[1].via == "10.0.0.1"
        assert entries[1].dev == "eth0"

    def test_resolve_vpn_domain_creates_tun0_entries(self) -> None:
        """Resolved VPN domain IPs become /32 entries through tun0."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock(spec=DnsResolver)
        mock_dns.available.return_value = True
        mock_dns.resolve_ipv4.return_value = ["9.9.9.9"]

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=[],
            bypass_subnets=[],
            vpn_domains=["vpn-only.example.com"],
            vpn_wildcards=[],
            vpn_subnets=[],
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        mock_dns.resolve_ipv4.assert_called_once_with("vpn-only.example.com", mock_shell)
        assert len(entries) == 1
        assert entries[0].subnet == "9.9.9.9/32"
        assert entries[0].via is None
        assert entries[0].dev == "tun0"

    def test_skips_domains_when_dns_unavailable(self) -> None:
        """Domains are skipped without attempting resolution when DNS is down."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock(spec=DnsResolver)
        mock_dns.available.return_value = False

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=["unreachable.com"],
            bypass_subnets=[],
            vpn_domains=["also-unreachable.com"],
            vpn_wildcards=[],
            vpn_subnets=["1.1.1.1/32"],
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        mock_dns.resolve_ipv4.assert_not_called()
        # Only the directly-specified subnet makes it
        assert len(entries) == 1
        assert entries[0].subnet == "1.1.1.1/32"

    def test_wildcard_expansion_resolves_across_tlds(self) -> None:
        """Wildcard patterns are expanded across common TLDs and resolved."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock(spec=DnsResolver)
        mock_dns.available.return_value = True
        # Each TLD resolves to a unique "IP" (the domain string) → no dedup
        mock_dns.resolve_ipv4.side_effect = lambda domain, shell: [domain]

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=[],
            bypass_subnets=[],
            vpn_domains=[],
            vpn_wildcards=["audiobookbay.*"],
            vpn_subnets=[],
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        # 11 TLDs, each resolves to a unique IP (the domain name) → no dedup
        assert len(entries) == 11
        for entry in entries:
            assert entry.via is None
            assert entry.dev == "tun0"

    def test_deduplication_across_sources(self) -> None:
        """Duplicate subnets across sources are deduplicated."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.read_text.return_value = "10.0.0.0/8\n"
        mock_dns = MagicMock()
        mock_dns.available.return_value = False

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=[],
            bypass_subnets=["10.0.0.0/8"],  # same as in RU cache
            vpn_domains=[],
            vpn_wildcards=[],
            vpn_subnets=["10.0.0.0/8"],  # same as in RU cache
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        # Only one entry: the RU cache one (first loaded)
        assert len(entries) == 1
        assert entries[0].subnet == "10.0.0.0/8"

    def test_empty_all_inputs_returns_empty_list(self) -> None:
        """No routes when all inputs are empty or unavailable."""
        mock_shell = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_dns = MagicMock()
        mock_dns.available.return_value = False

        loader = BypassLoader(mock_shell, mock_fs, mock_dns)
        entries = loader.load_all(
            ru_cache_path="/fake/cache",
            bypass_domains=[],
            bypass_subnets=[],
            vpn_domains=[],
            vpn_wildcards=[],
            vpn_subnets=[],
            gateway="10.0.0.1",
            interface="eth0",
            table_id="100",
        )
        assert entries == []
