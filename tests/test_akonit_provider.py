"""Tests for AkonitProvider — server listing, config generation, sanitization."""

from __future__ import annotations

import json

from vpn.adapters.akonit.provider import AkonitProvider
from vpn.config.core.servers import ServersConfig


def _fake_profile(tmp_path) -> str:
    """Write a synthetic sing-box profile built from the real server registry."""
    registry = ServersConfig._from_yaml().servers
    outbounds = [
        {
            "type": "vless",
            "tag": f"{entry.tag} ⚡",
            "server": "10.0.0.1",
            "server_port": 443,
        }
        for entry in registry.values()
    ]
    outbounds.append({"type": "urltest", "tag": "urltest_out", "outbounds": ["direct"]})
    outbounds.append({"type": "direct", "tag": "direct"})
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {"outbounds": outbounds, "route": {"final": "urltest_out", "rules": []}}
        )
    )
    return str(path)


class TestAkonitProvider:
    def test_lists_all_registered_servers(self, tmp_path) -> None:
        provider = AkonitProvider(_fake_profile(tmp_path))
        assert len(provider.list_servers()) == len(ServersConfig._from_yaml().servers)

    def test_get_server_by_name(self, tmp_path) -> None:
        provider = AkonitProvider(_fake_profile(tmp_path))
        server = provider.get_server("hellenteler")
        assert server.country == "de"
        assert "Хёллентэлер" in server.tag

    def test_build_singbox_config_returns_valid_json(self, tmp_path) -> None:
        provider = AkonitProvider(_fake_profile(tmp_path))
        config = json.loads(provider.build_singbox_config("hellenteler"))
        assert "outbounds" in config
        assert isinstance(config["outbounds"][0]["tag"], str)

    def test_sanitize_config_removes_statistics(self, tmp_path) -> None:
        raw = {"experimental": {"statistics": {"enabled": True}}}
        provider = AkonitProvider(_fake_profile(tmp_path))
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

    def test_route_final_matches_normalized_outbound(self, tmp_path) -> None:
        """After build+sanitize, route.final equals the target outbound tag (cleaned)."""
        provider = AkonitProvider(_fake_profile(tmp_path))
        config = json.loads(provider.build_singbox_config("hellenteler"))

        # route.final should be the cleaned outbound tag, not 'urltest_out'
        assert config["route"]["final"] != "urltest_out"
        # And it should match an actual outbound tag
        outbound_tags = [ob["tag"] for ob in config.get("outbounds", [])]
        assert config["route"]["final"] in outbound_tags


class TestSanitizeConfigDefaults:
    """Tests for sanitize_config() — stripping unsupported fields."""

    def test_strips_default_from_urltest(self, tmp_path) -> None:
        """'default' key is removed from urltest/selector outbounds."""
        provider = AkonitProvider(_fake_profile(tmp_path))
        raw = {
            "outbounds": [
                {"type": "urltest", "tag": "urltest_out", "default": "some-server", "outbounds": ["t1", "t2"]},
                {"type": "selector", "tag": "select", "default": "other", "outbounds": []},
            ]
        }
        result = provider.sanitize_config(raw)
        for ob in result["outbounds"]:
            assert "default" not in ob, f"outbound {ob['tag']} should not have 'default'"