"""Tests for configuration dataclasses loaded from YAML."""

from __future__ import annotations

from vpn.config.core.app import AppConfig
from vpn.config.core.bypass import BypassConfig
from vpn.config.core.health import HealthConfig
from vpn.config.core.network import NetworkConfig
from vpn.config.core.notification import NotificationConfig
from vpn.config.core.servers import ServersConfig
from vpn.config.core.tunnel import TunnelConfig
from vpn.config.core.vpn_routes import VpnRoutesConfig


class TestAppConfig:
    def test_loads_from_yaml(self) -> None:
        cfg = AppConfig._from_yaml()
        assert cfg.tag == "hiddify-vpn"
        assert cfg.table_id == "100"
        assert cfg.provider == "akonit"


class TestNetworkConfig:
    def test_loads_from_yaml(self) -> None:
        cfg = NetworkConfig._from_yaml()
        assert cfg.tun_address == "198.18.0.1/15"
        assert cfg.tun_mtu == 1360
        assert len(cfg.dns_servers) == 4
        assert len(cfg.lan_subnets) == 3


class TestHealthConfig:
    def test_loads_from_yaml(self) -> None:
        cfg = HealthConfig._from_yaml()
        assert cfg.fail_threshold == 3
        assert len(cfg.targets) >= 5
        assert len(cfg.user_agents) >= 3


class TestTunnelConfig:
    def test_loads_from_yaml(self) -> None:
        cfg = TunnelConfig._from_yaml()
        assert cfg.socks5_host == "127.0.0.1"
        assert cfg.socks5_port == 3066


class TestNotificationConfig:
    def test_loads_from_yaml(self) -> None:
        cfg = NotificationConfig._from_yaml()
        assert cfg.retries == 3
        assert "daemon_started" in cfg.events


class TestServersConfig:
    def test_loads_11_servers(self) -> None:
        cfg = ServersConfig._from_yaml()
        assert len(cfg.servers) == 11
        assert "barguzin" in cfg.servers
        assert "sirokko" in cfg.servers

    def test_server_entry_has_tag_and_country(self) -> None:
        cfg = ServersConfig._from_yaml()
        barguzin = cfg.servers["barguzin"]
        assert "Баргузин" in barguzin.tag
        assert barguzin.country == "ru"


class TestBypassConfig:
    def test_loads_from_yaml(self) -> None:
        cfg = BypassConfig._from_yaml()
        assert "api.deepseek.com" in cfg.domains


class TestVpnRoutesConfig:
    def test_loads_from_yaml(self) -> None:
        cfg = VpnRoutesConfig._from_yaml()
        assert "rutracker.org" in cfg.domains
        assert "audiobookbay.*" in cfg.wildcards
