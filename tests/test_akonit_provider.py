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
        # The first outbound tag varies per profile; just verify it's a non-empty string
        assert isinstance(config["outbounds"][0]["tag"], str)
        assert len(config["outbounds"][0]["tag"]) > 0

    def test_sanitize_config_removes_statistics(self) -> None:
        raw = {"experimental": {"statistics": {"enabled": True}}}
        provider = AkonitProvider(str(PROJECT_ROOT / "data" / "profile_keys_akonit_24_07_2026.json"))
        result = provider.sanitize_config(raw)
        assert "statistics" not in result.get("experimental", {})



class TestNormalizeTag:
    """Tests for _normalize_tag() — emoji stripping, whitespace collapsing."""

    _REAL_TAGS: list[tuple[str, str]] = [
        # (raw_tag_from_servers_yaml, expected_normalized)
        ("🇷🇺 Баргузин (Без рекламы)", "Баргузин"),
        ("🇷🇺 Алтай", "Алтай"),
        ("🇷🇺 Вилюй", "Вилюй"),
        ("🇷🇺 Магадан", "Магадан"),
        ("🇷🇺 Иркут", "Иркут"),
        ("🇷🇺 Амур", "Амур"),
        ("🇷🇺 Камчатка", "Камчатка"),
        ("🇷🇺 Таймыр", "Таймыр"),
        ("🇷🇺 Чукотка", "Чукотка"),
        ("🇷🇺 Сахалин", "Сахалин"),
        ("🇷🇺 Кольский", "Кольский"),
    ]

    def test_normalize_tag_all_11_servers(self) -> None:
        """Every real server tag normalizes to a plain, readable name."""
        for raw, expected in self._REAL_TAGS:
            result = AkonitProvider._normalize_tag(raw)
            assert result == expected, f"_normalize_tag({raw!r}) == {result!r}, expected {expected!r}"

    def test_already_clean_tag_unchanged(self) -> None:
        """Tags without emoji or boilerplate pass through unchanged."""
        assert AkonitProvider._normalize_tag("CleanTag") == "CleanTag"

    def test_emoji_only_tag(self) -> None:
        """Tags consisting purely of emoji become empty string."""
        assert AkonitProvider._normalize_tag("🇷🇺") == ""


class TestBuildSingboxConfig:
    """Tests for build_singbox_config() — route.final matching after sanitize."""

    def test_route_final_matches_normalized_outbound(self) -> None:
        """After build+sanitize, route.final equals the target outbound tag (cleaned)."""
        import json

        profile_path = str(PROJECT_ROOT / "data" / "profile_keys_akonit_24_07_2026.json")
        provider = AkonitProvider(profile_path)
        config_str = provider.build_singbox_config("barguzin")
        config = json.loads(config_str)

        # route.final should be the cleaned outbound tag, not 'urltest_out'
        assert config["route"]["final"] != "urltest_out"
        # And it should match an actual outbound tag
        outbound_tags = [ob["tag"] for ob in config.get("outbounds", [])]
        assert config["route"]["final"] in outbound_tags


class TestSanitizeConfigDefaults:
    """Tests for sanitize_config() — stripping unsupported fields."""

    def test_strips_default_from_urltest(self) -> None:
        """'default' key is removed from urltest/selector outbounds."""
        provider = AkonitProvider(str(PROJECT_ROOT / "data" / "profile_keys_akonit_24_07_2026.json"))
        raw = {
            "outbounds": [
                {"type": "urltest", "tag": "urltest_out", "default": "some-server", "outbounds": ["t1", "t2"]},
                {"type": "selector", "tag": "select", "default": "other", "outbounds": []},
            ]
        }
        result = provider.sanitize_config(raw)
        for ob in result["outbounds"]:
            assert "default" not in ob, f"outbound {ob['tag']} should not have 'default'"