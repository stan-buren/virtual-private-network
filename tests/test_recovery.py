"""Tests for tunnel verification and the recovery ladder."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vpn.core.health.checker import HealthChecker
from vpn.core.orchestrator import VpnOrchestrator


def _result(stdout: str = "", returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, returncode=returncode)


def _shell(results: list) -> MagicMock:
    shell = MagicMock()
    shell.run.side_effect = results
    return shell


def _orch(shell, provider=None, paths=None) -> VpnOrchestrator:
    orch = VpnOrchestrator.__new__(VpnOrchestrator)
    orch._shell = shell
    orch._provider = provider or MagicMock()
    orch._paths = paths if paths is not None else {}
    orch._tunnel_cfg = SimpleNamespace(socks5_host="127.0.0.1", socks5_port=3066)
    orch._app_cfg = SimpleNamespace(table_id="100")
    orch._rules = MagicMock()
    orch._deployer = MagicMock()
    return orch


class TestHealthCheckerTunnelProbe:
    """The checker must judge the tunnel, not "internet in general"."""

    def test_tun_down_is_failure(self) -> None:
        checker = HealthChecker(
            _shell([_result("tun0 DOWN")]), ["https://example.com"], ["ua"], sample_size=1
        )
        assert checker._check() is False

    def test_probe_goes_through_socks_and_accepts_any_status(self) -> None:
        shell = _shell([_result("tun0 UP 198.18.0.1/15"), _result("403")])
        checker = HealthChecker(
            shell, ["https://example.com"], ["ua"], sample_size=1
        )
        assert checker._check() is True
        command = shell.run.call_args_list[-1].args[0]
        assert "--socks5-hostname 127.0.0.1:3066" in command

    def test_zero_code_is_failure(self) -> None:
        shell = _shell([
            _result("tun0 UP 198.18.0.1/15"),
            _result("000"),
        ])
        checker = HealthChecker(
            shell, ["https://example.com"], ["ua"], sample_size=1
        )
        assert checker._check() is False


class TestVerifyTunnel:
    def test_ok_when_tun_up_and_probe_answers(self) -> None:
        orch = _orch(_shell([_result("tun0 UP 198.18.0.1/15"), _result("200")]))
        assert orch._verify_tunnel_sync(5) is True

    def test_tun_down_is_failure(self) -> None:
        orch = _orch(_shell([_result("tun0 DOWN")]))
        assert orch._verify_tunnel_sync(5) is False

    def test_no_probe_answer_is_failure(self) -> None:
        orch = _orch(_shell([
            _result("tun0 UP"),
            _result("000"),
            _result("tun0 UP"),
            _result("000"),
        ]))
        assert orch._verify_tunnel_sync(5) is False

    def test_http_error_status_still_proves_the_tunnel(self) -> None:
        orch = _orch(_shell([_result("tun0 UP"), _result("403")]))
        assert orch._verify_tunnel_sync(5) is True

    @pytest.mark.asyncio
    async def test_restart_and_verify_reports_verification(self) -> None:
        orch = _orch(MagicMock())
        orch.restart_tunnel = AsyncMock()
        orch.verify_tunnel = AsyncMock(return_value=True)
        assert await orch.restart_and_verify(MagicMock()) is True
        orch.restart_tunnel.assert_awaited_once()


class TestRotateServer:
    @pytest.mark.asyncio
    async def test_skips_unreachable_node_and_verifies_the_next(self, tmp_path) -> None:
        config = tmp_path / "config.json"
        # The active outbound is a node that is no longer in the catalog, so
        # neither candidate is skipped as "current" before the TCP probe.
        config.write_text(json.dumps({"outbounds": [{"tag": "urltest_out", "default": "old"}]}))
        provider = MagicMock()
        provider.list_servers.return_value = [
            SimpleNamespace(name="dead", tag="dead", country="DE", host="10.0.0.1", port=443),
            SimpleNamespace(name="live", tag="live", country="NL", host="10.0.0.2", port=443),
        ]
        provider.build_singbox_config.return_value = '{"outbounds": []}'
        orch = _orch(MagicMock(), provider, {"sing_box_config": str(config)})
        orch._tcp_reachable = MagicMock(side_effect=[False, True])
        orch.restart_tunnel = AsyncMock()
        orch.verify_tunnel = AsyncMock(return_value=True)
        ctx = MagicMock()

        assert await orch.rotate_and_restart(ctx) is True
        assert ctx.active_server == "live"
        assert config.read_text() == '{"outbounds": []}'

    @pytest.mark.asyncio
    async def test_returns_false_when_no_node_is_reachable(self) -> None:
        provider = MagicMock()
        provider.list_servers.return_value = [
            SimpleNamespace(name="a", tag="a", country="DE", host="10.0.0.1", port=443),
        ]
        orch = _orch(MagicMock(), provider)
        orch._tcp_reachable = MagicMock(return_value=False)
        assert await orch.rotate_and_restart(MagicMock()) is False

    def test_current_outbound_tag_reads_urltest_default(self, tmp_path) -> None:
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"outbounds": [{"tag": "urltest_out", "default": "x"}]}))
        orch = _orch(MagicMock(), paths={"sing_box_config": str(config)})
        assert orch._current_outbound_tag() == "x"


class TestRefreshSubscription:
    @pytest.mark.asyncio
    async def test_downloads_applies_redeploys_and_verifies(self, tmp_path) -> None:
        orch = _orch(_shell([_result("{}", 0)]), paths={"sing_box_config": str(tmp_path / "config.json")})
        orch.restart_tunnel = AsyncMock()
        orch.verify_tunnel = AsyncMock(return_value=True)
        updater = MagicMock()
        updater.apply.return_value = {"server_count": 4}
        fs = MagicMock()
        fs.read_json.return_value = {}
        subscription = SimpleNamespace(url="https://sub.example/import/karing/1")

        with patch("vpn.config.config_loader.get_subscription_config", return_value=subscription), \
             patch("vpn.config.paths.PROJECT_ROOT", tmp_path), \
             patch("vpn.config.paths.load_paths_config", return_value={"profile_keys": "data/profile.json"}), \
             patch("vpn.adapters.system.filesystem.FilesystemAdapter", return_value=fs), \
             patch("vpn.core.subscription.SubscriptionUpdater", return_value=updater), \
             patch("vpn.core.orchestrator.socket.getaddrinfo", return_value=[]):
            assert await orch.refresh_and_restart(MagicMock()) is True

        updater.apply.assert_called_once()
        orch._deployer.deploy.assert_called_once()
        orch.restart_tunnel.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_url_is_failure(self) -> None:
        orch = _orch(MagicMock())
        with patch(
            "vpn.config.config_loader.get_subscription_config",
            return_value=SimpleNamespace(url=""),
        ):
            assert await orch.refresh_and_restart(MagicMock()) is False
