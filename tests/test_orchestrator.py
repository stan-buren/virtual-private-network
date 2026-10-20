"""Tests for VpnOrchestrator bootstrap sequence ordering and tunnel restart."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from vpn.core.events import EventType, VpnEvent
from vpn.core.orchestrator import VpnOrchestrator
from vpn.core.state_machine.context import RuntimeContext
from vpn.logger.exceptions import VpnConnectionError


def _mock_orch(**overrides):
    """Factory for a fully-mocked VpnOrchestrator."""
    defaults = {
        "deployer": MagicMock(),
        "topology_discovery": MagicMock(),
        "resolver": MagicMock(),
        "tun": MagicMock(),
        "rules": MagicMock(),
        "route_table": MagicMock(),
        "bypass_loader": MagicMock(),
        "nat": MagicMock(),
        "mss": MagicMock(),
        "sysctl_mgr": MagicMock(),
        "tun2socks": MagicMock(),
        "provider": MagicMock(),
        "notifier": MagicMock(),
        "ru_updater": MagicMock(run_forever=AsyncMock()),
        "watcher": MagicMock(),
        "shell": MagicMock(),
        "subprocess": MagicMock(),
        "app_cfg": MagicMock(table_id="100"),
        "net_cfg": MagicMock(dns_servers=[], lan_subnets=[]),
        "tunnel_cfg": MagicMock(socks5_host="127.0.0.1", socks5_port=3066),
        "bypass_cfg": MagicMock(domains=[], subnets=[]),
        "vpn_routes_cfg": MagicMock(domains=[], wildcards=[], subnets=[]),
        "paths": {},
    }
    defaults.update(overrides)
    return VpnOrchestrator(**defaults)


class TestOrchestratorBootstrap:
    """Tests for the bootstrap SEQUENCE, not process monitoring."""

    @pytest.mark.asyncio
    async def test_bootstrap_posts_bootstrap_done(self) -> None:
        ctx = RuntimeContext()
        events: asyncio.Queue[VpnEvent] = asyncio.Queue()
        orch = _mock_orch()
        await orch.bootstrap(ctx, events)
        event = events.get_nowait()
        assert event.type == EventType.BOOTSTRAP_DONE

    @pytest.mark.asyncio
    async def test_bootstrap_populates_context(self) -> None:
        ctx = RuntimeContext()
        events: asyncio.Queue[VpnEvent] = asyncio.Queue()
        mock_topo = MagicMock()
        mock_topo.discover.return_value = MagicMock(gateway="10.0.0.1", interface="eth0")
        orch = _mock_orch(topology_discovery=mock_topo)
        await orch.bootstrap(ctx, events)
        assert ctx.gateway == "10.0.0.1"
        assert ctx.interface == "eth0"

    @pytest.mark.asyncio
    async def test_bootstrap_supervises_both_processes(self) -> None:
        """Bootstrap must hand both children to the watcher."""
        ctx = RuntimeContext()
        events: asyncio.Queue[VpnEvent] = asyncio.Queue()
        watcher = MagicMock()
        orch = _mock_orch(watcher=watcher)
        await orch.bootstrap(ctx, events)
        watched = [call.args[0] for call in watcher.watch.call_args_list]
        assert watched == [EventType.SINGBOX_DIED, EventType.TUNNEL_DIED]


class TestOrchestratorRestartTunnel:
    """Tests for the shared restart path used by recovery and server switches."""

    @pytest.mark.asyncio
    async def test_restart_replaces_processes_and_reasserts_routing(self) -> None:
        ctx = RuntimeContext()
        watcher = MagicMock()
        tun2socks = MagicMock()
        shell = MagicMock()
        orch = _mock_orch(watcher=watcher, tun2socks=tun2socks, shell=shell)
        await orch.restart_tunnel(ctx)
        watcher.unwatch.assert_any_call(EventType.SINGBOX_DIED)
        watcher.unwatch.assert_any_call(EventType.TUNNEL_DIED)
        assert ctx.singbox is not None
        assert ctx.tun2socks is not None
        tun2socks.start.assert_called_once_with("socks5://127.0.0.1:3066")
        assert watcher.watch.call_count == 2
        # The tun device is destroyed and rebuilt so the new tun2socks starts
        # from a clean device instead of one whose route is stuck "linkdown".
        orch._tun.destroy.assert_called_once()
        orch._tun.create.assert_called_once()
        # Deleting tun0 drops its default route from table 100 - re-assert it.
        orch._route_table.set_default.assert_any_call("100")
        # The rule set is kernel state that a netplan apply, an interface
        # reconfiguration or a DHCP renewal wipes silently. A restart that only
        # respawns processes recreates a tunnel nobody's traffic enters, so the
        # catch-all has to be proven again on every restart.
        orch._rules.add_catchall.assert_called_with("100")
        # The destructive teardown path stays bootstrap-only.
        orch._rules.clear_all.assert_not_called()
        orch._route_table.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_for_socks_port_raises_when_never_open(self) -> None:
        orch = _mock_orch()
        with pytest.raises(VpnConnectionError):
            await orch._wait_for_socks_port(timeout=0)

    @pytest.mark.asyncio
    async def test_restart_propagates_missing_listener(self) -> None:
        shell = MagicMock()
        shell.run.return_value = MagicMock(stdout="")
        orch = _mock_orch(shell=shell)
        with pytest.raises(VpnConnectionError):
            await orch.restart_tunnel(RuntimeContext())
