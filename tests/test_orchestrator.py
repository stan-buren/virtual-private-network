"""Tests for VpnOrchestrator bootstrap sequence ordering."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from vpn.core.events import EventType, VpnEvent
from vpn.core.orchestrator import VpnOrchestrator
from vpn.core.state_machine.context import RuntimeContext


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
        "shell": MagicMock(),
        "app_cfg": MagicMock(table_id="100"),
        "net_cfg": MagicMock(dns_servers=[], lan_subnets=[]),
        "tunnel_cfg": MagicMock(socks5_host="127.0.0.1", socks5_port=3066),
        "bypass_cfg": MagicMock(domains=[], subnets=[]),
        "vpn_routes_cfg": MagicMock(domains=[], wildcards=[], subnets=[]),
        "paths": {},
    }
    defaults.update(overrides)
    return VpnOrchestrator(**defaults)


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_bootstrap_posts_bootstrap_done(self) -> None:
        """Verify BOOTSTRAP_DONE event is posted after bootstrap."""
        ctx = RuntimeContext()
        events: asyncio.Queue[VpnEvent] = asyncio.Queue()
        orch = _mock_orch()
        await orch.bootstrap(ctx, events)
        event = events.get_nowait()
        assert event.type == EventType.BOOTSTRAP_DONE

    @pytest.mark.asyncio
    async def test_bootstrap_populates_context(self) -> None:
        """Verify gateway and interface are set in RuntimeContext."""
        ctx = RuntimeContext()
        events: asyncio.Queue[VpnEvent] = asyncio.Queue()
        mock_topo = MagicMock()
        mock_topo.discover.return_value = MagicMock(gateway="10.0.0.1", interface="eth0")
        orch = _mock_orch(topology_discovery=mock_topo)
        await orch.bootstrap(ctx, events)
        assert ctx.gateway == "10.0.0.1"
        assert ctx.interface == "eth0"
