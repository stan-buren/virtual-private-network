"""Tests for AkonitProvider — server listing, config generation, sanitization."""

from __future__ import annotations

from vpn.adapters.akonit.provider import AkonitProvider
from vpn.config.paths import PROJECT_ROOT


class TestAkonitProvider:
    def test_lists_11_servers(self) -> None:
        profile_path = str(PROJECT_ROOT / "data" / "profile_keys_akonit_24_07_2026.json")
        provider = AkonitProvider(profile_path)
        servers = provider.list_servers()
        assert len(servers) == 11

    def test_get_barguzin_server(self) -> None:
        profile_path = str(PROJECT_ROOT / "data" / "profile_keys_akonit_24_07_2026.json")
        provider = AkonitProvider(profile_path)
        server = provider.get_server("barguzin")
        assert server.country == "ru"
        assert "Баргузин" in server.tag

    def test_build_singbox_config_returns_valid_json(self) -> None:
        import json
        profile_path = str(PROJECT_ROOT / "data" / "profile_keys_akonit_24_07_2026.json")
        provider = AkonitProvider(profile_path)
        config_str = provider.build_singbox_config("barguzin")
        config = json.loads(config_str)
        assert "outbounds" in config
        outbounds = config["outbounds"]
        assert outbounds[0]["tag"] == "vless-out"

    def test_sanitize_config_removes_statistics(self) -> None:
        raw = {"experimental": {"statistics": {"enabled": True}}}
        provider = AkonitProvider(str(PROJECT_ROOT / "data" / "profile_keys_akonit_24_07_2026.json"))
        result = provider.sanitize_config(raw)
        assert "statistics" not in result.get("experimental", {})
