"""Tests for server switcher and config deployer."""

from __future__ import annotations

from unittest.mock import MagicMock

from vpn.core.ports import ServerInfo
from vpn.core.server_manager.deployer import ConfigDeployer
from vpn.core.server_manager.switcher import ServerSwitcher


class TestConfigDeployer:
    """Tests for ConfigDeployer — profile copy, sanitize, error handling."""

    def test_deploy_returns_false_when_no_profile_and_no_config(self) -> None:
        """Neither profile nor config exist — deploy fails gracefully."""
        mock_provider = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False

        deployer = ConfigDeployer(mock_provider, mock_fs, "/fake/profile", "/fake/config")
        result = deployer.deploy()

        assert result is False
        mock_fs.copy.assert_not_called()
        mock_fs.read_text.assert_not_called()
        mock_provider.sanitize_config.assert_not_called()

    def test_deploy_sanitizes_existing_config_when_no_profile(self) -> None:
        """Profile missing but config exists — sanitize in-place, succeed."""
        mock_provider = MagicMock()
        mock_provider.sanitize_config.return_value = {"sanitized": True}
        mock_fs = MagicMock()
        mock_fs.exists.side_effect = lambda p: p == "/fake/config"
        mock_fs.read_text.return_value = '{"key": "value"}'

        deployer = ConfigDeployer(mock_provider, mock_fs, "/fake/profile", "/fake/config")
        result = deployer.deploy()

        assert result is True
        mock_fs.copy.assert_not_called()
        mock_fs.read_text.assert_called_once_with("/fake/config")
        mock_provider.sanitize_config.assert_called_once_with({"key": "value"})
        mock_fs.write_text.assert_called_once()

    def test_deploy_copies_profile_then_sanitizes(self) -> None:
        """Profile file exists — copy it, then sanitize, succeed."""
        mock_provider = MagicMock()
        mock_provider.sanitize_config.return_value = {"clean": True}
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.read_text.return_value = '{"raw": "data"}'

        deployer = ConfigDeployer(mock_provider, mock_fs, "/fake/profile", "/fake/config")
        result = deployer.deploy()

        assert result is True
        mock_fs.copy.assert_called_once_with("/fake/profile", "/fake/config")
        mock_fs.read_text.assert_called_once_with("/fake/config")
        mock_provider.sanitize_config.assert_called_once_with({"raw": "data"})
        mock_fs.write_text.assert_called_once()

    def test_deploy_returns_false_on_sanitization_failure(self) -> None:
        """Sanitize raises — deploy returns False, does not crash."""
        mock_provider = MagicMock()
        mock_provider.sanitize_config.side_effect = RuntimeError("bad config")
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.read_text.return_value = '{"broken": true}'

        deployer = ConfigDeployer(mock_provider, mock_fs, "/fake/profile", "/fake/config")
        result = deployer.deploy()

        assert result is False
        # write_text must not be called after sanitize failure
        mock_fs.write_text.assert_not_called()


class TestServerSwitcher:
    """Tests for ServerSwitcher — server switch, list, current tag detection."""

    def test_list_servers_delegates_to_provider(self) -> None:
        """list_servers returns exactly what the provider returns."""
        mock_provider = MagicMock()
        mock_provider.list_servers.return_value = []
        mock_fs = MagicMock()
        mock_shell = MagicMock()

        switcher = ServerSwitcher(mock_provider, mock_fs, mock_shell, "/fake/config")
        servers = switcher.list_servers()

        assert servers == []
        mock_provider.list_servers.assert_called_once()

    def test_switch_writes_config_and_returns_tag(self) -> None:
        """Happy path: build config, write, restart, return new tag."""
        mock_provider = MagicMock()
        mock_provider.build_singbox_config.return_value = '{"outbounds":[]}'
        mock_provider.get_server.return_value = ServerInfo(
            name="barguzin",
            tag="barguzin-vless",
            country="ru",
            host="10.0.0.1",
            port=443,
        )
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_shell = MagicMock()

        switcher = ServerSwitcher(mock_provider, mock_fs, mock_shell, "/fake/config")
        tag = switcher.switch("barguzin")

        assert tag == "barguzin-vless"
        mock_provider.build_singbox_config.assert_called_once_with("barguzin")
        mock_fs.write_text.assert_called_once_with("/fake/config", '{"outbounds":[]}')
        mock_shell.run.assert_called_once()

    def test_switch_does_not_restart_when_restart_service_false(self) -> None:
        """restart_service=False — skip pkill, still write config."""
        mock_provider = MagicMock()
        mock_provider.build_singbox_config.return_value = '{}'
        mock_provider.get_server.return_value = ServerInfo(
            name="test-server",
            tag="test-tag",
            country="nl",
            host="10.0.0.2",
            port=443,
        )
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_shell = MagicMock()

        switcher = ServerSwitcher(mock_provider, mock_fs, mock_shell, "/fake/config")
        tag = switcher.switch("test", restart_service=False)

        assert tag == "test-tag"
        mock_shell.run.assert_not_called()

    def test_switch_raises_keyerror_for_unknown_server(self) -> None:
        """Provider raises KeyError — switch propagates it."""
        mock_provider = MagicMock()
        mock_provider.build_singbox_config.side_effect = KeyError("unknown")
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_shell = MagicMock()

        switcher = ServerSwitcher(mock_provider, mock_fs, mock_shell, "/fake/config")

        import pytest
        with pytest.raises(KeyError, match="unknown"):
            switcher.switch("nonexistent")

    def test_current_server_tag_returns_none_when_no_config(self) -> None:
        """Config file missing — _current_server_tag returns None."""
        mock_provider = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = False
        mock_shell = MagicMock()

        switcher = ServerSwitcher(mock_provider, mock_fs, mock_shell, "/fake/config")
        tag = switcher._current_server_tag()

        assert tag is None
        mock_fs.read_json.assert_not_called()

    def test_current_server_tag_reads_vless_out_server_field(self) -> None:
        """Config with vless-out outbound — returns server field value."""
        mock_provider = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.read_json.return_value = {
            "outbounds": [
                {"tag": "direct"},
                {"tag": "vless-out", "server": "ams-nl-01.akonit.net"},
                {"tag": "dns"},
            ],
        }
        mock_shell = MagicMock()

        switcher = ServerSwitcher(mock_provider, mock_fs, mock_shell, "/fake/config")
        tag = switcher._current_server_tag()

        assert tag == "ams-nl-01.akonit.net"

    def test_current_server_tag_returns_none_when_no_vless_outbound(self) -> None:
        """Config lacks a vless-out tag — _current_server_tag returns None."""
        mock_provider = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.read_json.return_value = {
            "outbounds": [
                {"tag": "direct"},
                {"tag": "dns"},
            ],
        }
        mock_shell = MagicMock()

        switcher = ServerSwitcher(mock_provider, mock_fs, mock_shell, "/fake/config")
        tag = switcher._current_server_tag()

        assert tag is None

    def test_current_server_tag_returns_none_on_json_read_failure(self) -> None:
        """read_json raises — graceful None, no crash."""
        mock_provider = MagicMock()
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        mock_fs.read_json.side_effect = OSError("permission denied")
        mock_shell = MagicMock()

        switcher = ServerSwitcher(mock_provider, mock_fs, mock_shell, "/fake/config")
        tag = switcher._current_server_tag()

        assert tag is None
