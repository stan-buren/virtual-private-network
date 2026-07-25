"""Tests for routing modules — rule manager, tun interface, route table."""

from __future__ import annotations

from unittest.mock import MagicMock

from vpn.core.routing.route_table import RouteEntry, RouteTable
from vpn.core.routing.rule_manager import (
    PRIO_CATCHALL,
    PRIO_DNS_START,
    PRIO_DNS_END,
    PRIO_LAN_START,
    PRIO_LAN_END,
    PRIO_SERVER_IPS,
    PRIO_TORRENT,
    RuleManager,
)
from vpn.core.routing.tun_interface import TunInterface


class TestRuleManager:
    """Tests for RuleManager — ip rule lifecycle and priority constants."""

    # Priority constants

    def test_priority_constants_are_correct(self) -> None:
        """All priority constants match the documented schema."""
        assert PRIO_SERVER_IPS == 1
        assert PRIO_DNS_START == 3
        assert PRIO_DNS_END == 6
        assert PRIO_LAN_START == 10
        assert PRIO_LAN_END == 12
        assert PRIO_TORRENT == 20
        assert PRIO_CATCHALL == 30

    def test_priority_constants_are_monotonic(self) -> None:
        """Lower numeric priority means higher routing precedence."""
        assert PRIO_SERVER_IPS < PRIO_DNS_START
        assert PRIO_DNS_END < PRIO_LAN_START
        assert PRIO_LAN_END < PRIO_TORRENT
        assert PRIO_TORRENT < PRIO_CATCHALL

    # server bypass

    def test_add_server_bypass_calls_shell(self) -> None:
        """Adding a server bypass issues delete-then-add ip rule commands."""
        mock_shell = MagicMock()
        rm = RuleManager(mock_shell)
        rm.add_server_bypass("1.2.3.4")
        assert mock_shell.run.call_count == 2

    # dns bypass

    def test_add_dns_bypass_calls_shell(self) -> None:
        """Adding a DNS bypass issues delete-then-add ip rule commands."""
        mock_shell = MagicMock()
        rm = RuleManager(mock_shell)
        rm.add_dns_bypass("8.8.8.8", priority=5)
        assert mock_shell.run.call_count == 2

    # lan bypass

    def test_add_lan_bypass_calls_shell(self) -> None:
        """Adding a LAN bypass issues a single ip rule add command."""
        mock_shell = MagicMock()
        rm = RuleManager(mock_shell)
        rm.add_lan_bypass("192.168.0.0/16", priority=11)
        assert mock_shell.run.call_count == 1

    # torrent bypass

    def test_add_torrent_bypass_calls_shell(self) -> None:
        """Adding torrent bypass issues delete-then-add fwmark rules."""
        mock_shell = MagicMock()
        rm = RuleManager(mock_shell)
        rm.add_torrent_bypass()
        assert mock_shell.run.call_count == 2

    # catchall

    def test_add_catchall_calls_shell(self) -> None:
        """Catch-all adds a single 'from all table <id>' rule."""
        mock_shell = MagicMock()
        rm = RuleManager(mock_shell)
        rm.add_catchall("100")
        mock_shell.run.assert_called_once()

    # clear methods

    def test_clear_all_calls_shell(self) -> None:
        """clear_all removes priority 1 rules in a loop then 2–30 individually."""
        mock_shell = MagicMock()
        rm = RuleManager(mock_shell)
        rm.clear_all()
        # 1 loop call + 29 single-priority calls (2 through 30)
        assert mock_shell.run.call_count == 30

    def test_clear_server_bypasses_calls_shell(self) -> None:
        """clear_server_bypasses removes priority 1 rules in a loop."""
        mock_shell = MagicMock()
        rm = RuleManager(mock_shell)
        rm.clear_server_bypasses()
        assert mock_shell.run.call_count == 1


class TestTunInterface:
    """Tests for TunInterface — tun0 create and destroy lifecycle."""

    def test_create_calls_shell(self) -> None:
        """create() issues tuntap add, addr add, and link set commands."""
        mock_shell = MagicMock()
        tun = TunInterface(mock_shell)
        tun.create()
        assert mock_shell.run.call_count == 3

    def test_destroy_calls_shell(self) -> None:
        """destroy() issues link down and tuntap del commands."""
        mock_shell = MagicMock()
        tun = TunInterface(mock_shell)
        tun.destroy()
        assert mock_shell.run.call_count == 2

    def test_default_address_and_mtu(self) -> None:
        """Default constructor uses 198.18.0.1/15 and MTU 1360."""
        mock_shell = MagicMock()
        tun = TunInterface(mock_shell)
        assert tun._address == "198.18.0.1/15"
        assert tun._mtu == 1360

    def test_custom_address_and_mtu(self) -> None:
        """Constructor accepts custom address and MTU."""
        mock_shell = MagicMock()
        tun = TunInterface(mock_shell, address="10.0.0.1/24", mtu=1500)
        assert tun._address == "10.0.0.1/24"
        assert tun._mtu == 1500


class TestRouteEntry:
    """Tests for RouteEntry — frozen dataclass representing a routing rule."""

    def test_frozen_dataclass(self) -> None:
        """All fields are accessible and hold the values passed at construction."""
        entry = RouteEntry(
            subnet="10.0.0.0/8", via="192.168.1.1", dev="eth0", table_id="100",
        )
        assert entry.subnet == "10.0.0.0/8"
        assert entry.via == "192.168.1.1"
        assert entry.dev == "eth0"
        assert entry.table_id == "100"

    def test_via_none(self) -> None:
        """The via field accepts None for direct routes (e.g. tun0)."""
        entry = RouteEntry(
            subnet="0.0.0.0/0", via=None, dev="tun0", table_id="100",
        )
        assert entry.via is None

    def test_is_hashable(self) -> None:
        """Frozen dataclass instances are hashable — usable in sets/dicts."""
        a = RouteEntry(subnet="10.0.0.0/8", via="192.168.1.1", dev="eth0", table_id="100")
        b = RouteEntry(subnet="10.0.0.0/8", via="192.168.1.1", dev="eth0", table_id="100")
        assert a == b
        assert hash(a) == hash(b)


class TestRouteTable:
    """Tests for RouteTable — batch route injection, defaults, and flushing."""

    def test_load_batch_empty_returns_zero(self) -> None:
        """An empty entry list must not call the shell and returns 0."""
        mock_shell = MagicMock()
        rt = RouteTable(mock_shell)
        count = rt.load_batch([], "100")
        assert count == 0
        mock_shell.run.assert_not_called()

    def test_load_batch_nonempty_calls_shell(self) -> None:
        """Non-empty entries must invoke 'ip -force -batch' against a temp file."""
        mock_shell = MagicMock()
        rt = RouteTable(mock_shell)
        entries = [
            RouteEntry(subnet="10.0.0.0/8", via="192.168.1.1", dev="eth0", table_id="100"),
            RouteEntry(subnet="172.16.0.0/12", via=None, dev="tun0", table_id="100"),
        ]
        count = rt.load_batch(entries, "100")
        assert count == 2
        mock_shell.run.assert_called_once()

    def test_set_default_calls_shell(self) -> None:
        """set_default sets 'default dev tun0' in the given table."""
        mock_shell = MagicMock()
        rt = RouteTable(mock_shell)
        rt.set_default("100")
        mock_shell.run.assert_called_once()

    def test_flush_calls_shell(self) -> None:
        """flush removes all routes from the given table."""
        mock_shell = MagicMock()
        rt = RouteTable(mock_shell)
        rt.flush("100")
        mock_shell.run.assert_called_once()
