"""Tests for the subscription updater and the config update CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from vpn.adapters.system.filesystem import FilesystemAdapter
from vpn.cli.main import cli
from vpn.core.subscription import (
    SubscriptionError,
    SubscriptionUpdater,
    merge_profile,
    normalize_profile,
    validate_profile,
)

PROFILE = {
    "log": {"level": "warn"},
    "outbounds": [
        {"type": "vless", "tag": "de", "server": "1.2.3.4", "server_port": 443},
        {"type": "vless", "tag": "nl", "server": "5.6.7.8", "server_port": 443},
        {"type": "direct", "tag": "direct"},
    ],
}


BASELINE = {
    "inbounds": [
        {"type": "mixed", "tag": "mixed_in_proxy", "listen_port": 3066},
    ]
}


class TestNormalize:
    def test_renames_group(self):
        prof = {
            "outbounds": [
                {"type": "urltest", "tag": "auto", "outbounds": ["a"]},
                {"type": "vless", "tag": "a"},
            ],
            "route": {"final": "auto", "rules": [{"outbound": "auto"}]},
            "dns": {"servers": [{"tag": "dns-remote", "detour": "auto"}]},
        }
        out = normalize_profile(prof)
        assert out["outbounds"][0]["tag"] == "urltest_out"
        assert out["route"]["final"] == "urltest_out"
        assert out["route"]["rules"][0]["outbound"] == "urltest_out"
        assert out["dns"]["servers"][0]["detour"] == "urltest_out"

    def test_merge_adds_baseline_inbounds(self):
        prof = {"outbounds": [{"type": "vless", "tag": "x"}], "route": {}}
        out = merge_profile(prof, BASELINE)
        assert out["inbounds"][0]["listen_port"] == 3066
        assert out["outbounds"][0]["tag"] == "x"


class TestValidateProfile:
    def test_valid(self):
        assert validate_profile(json.dumps(PROFILE))["outbounds"]

    def test_not_json(self):
        with pytest.raises(SubscriptionError):
            validate_profile("<html>nope</html>")

    def test_no_outbounds(self):
        with pytest.raises(SubscriptionError):
            validate_profile("{}")

    def test_no_vless(self):
        with pytest.raises(SubscriptionError):
            validate_profile(json.dumps({"outbounds": [{"type": "direct"}]}))


class TestUpdater:
    def test_apply_writes_and_prunes(self, tmp_path):
        target = tmp_path / "data" / "profile.json"
        legacy1 = tmp_path / "data" / "profile_keys_akonit_21_09_2026.json"
        legacy2 = tmp_path / "data" / "profile_keys_akonit_24_07_2026.json"
        legacy1.parent.mkdir(parents=True)
        legacy1.write_text("old")
        legacy2.write_text("old")

        updater = SubscriptionUpdater(
            FilesystemAdapter(),
            str(target),
            legacy_patterns=[
                str(tmp_path / "data" / "profile_keys_*.json"),
                str(tmp_path / "data" / "profile*.json"),
            ],
            baseline=BASELINE,
        )
        summary = updater.apply(json.dumps(PROFILE))

        assert summary["server_count"] == 2
        assert summary["has_inbounds"] is True
        assert target.exists()
        assert not legacy1.exists()
        assert not legacy2.exists()
        written = json.loads(target.read_text())
        assert written["outbounds"][0]["tag"] == "de"

    def test_apply_invalid(self, tmp_path):
        updater = SubscriptionUpdater(FilesystemAdapter(), str(tmp_path / "p.json"))
        with pytest.raises(SubscriptionError):
            updater.apply("not json")


class TestConfigUpdateCli:
    def test_update_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("vpn.cli.main.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "vpn.cli.main.load_paths_config",
            lambda root: {"profile_keys": "data/profile.json"},
        )

        class FakeConfig:
            url = "https://example/sub"

        monkeypatch.setattr(
            "vpn.config.config_loader.get_subscription_config", lambda: FakeConfig()
        )

        class FakeResult:
            returncode = 0
            stdout = json.dumps(PROFILE)

        monkeypatch.setattr(
            "vpn.cli.main.ShellAdapter", lambda: type("S", (), {"run": lambda *a, **k: FakeResult()})()
        )
        monkeypatch.setattr(
            "vpn.cli.main.ipc_call", lambda method, params=None: {"server": "de", "count": 2}
        )

        result = CliRunner().invoke(cli, ["config", "update"])
        assert result.exit_code == 0
        assert "Profile updated" in result.output
        assert (tmp_path / "data" / "profile.json").exists()

    def test_update_download_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr("vpn.cli.main.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("vpn.cli.main.load_paths_config", lambda root: {})

        class FakeConfig:
            url = "https://example/sub"

        monkeypatch.setattr(
            "vpn.config.config_loader.get_subscription_config", lambda: FakeConfig()
        )

        class FakeResult:
            returncode = 22
            stdout = ""

        monkeypatch.setattr(
            "vpn.cli.main.ShellAdapter", lambda: type("S", (), {"run": lambda *a, **k: FakeResult()})()
        )
        result = CliRunner().invoke(cli, ["config", "update"])
        assert result.exit_code == 1

    def test_update_no_url(self, tmp_path, monkeypatch):
        monkeypatch.setattr("vpn.cli.main.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("vpn.cli.main.load_paths_config", lambda root: {})

        class FakeConfig:
            url = ""

        monkeypatch.setattr(
            "vpn.config.config_loader.get_subscription_config", lambda: FakeConfig()
        )
        result = CliRunner().invoke(cli, ["config", "update"])
        assert result.exit_code == 1

