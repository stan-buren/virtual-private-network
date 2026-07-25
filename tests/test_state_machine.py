"""Tests for state machine — transitions, timeouts, fail streak."""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from typing import Iterator, Type

import pytest

from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.context import RuntimeContext
from vpn.core.state_machine.machine import VpnStateMachine
from vpn.core.state_machine.states.base import VpnState
from vpn.core.state_machine.states.bootstrapping import BootstrappingState
from vpn.core.state_machine.states.degraded import DegradedState
from vpn.core.state_machine.states.failed import FailedState
from vpn.core.state_machine.states.healthy import HealthyState
from vpn.core.state_machine.states.restarting import RestartingState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _patch_exit() -> Iterator[None]:
    """Context manager that prevents sys.exit from aborting the test process."""
    original = sys.exit
    sys.exit = lambda code=0: None  # type: ignore[assignment]
    try:
        yield
    finally:
        sys.exit = original  # type: ignore[assignment]


async def _transition_to(machine: VpnStateMachine, state_cls: Type[VpnState]) -> None:
    """Transition into *state_cls*; wraps sys.exit for FailedState destinations."""
    with _patch_exit():
        await machine.transition_to(state_cls)




def _mock_orchestrator(machine: VpnStateMachine) -> None:
    """Set minimal orchestrator mock so BootstrappingState.on_enter() doesn't crash."""
    from unittest.mock import AsyncMock, MagicMock
    orch = MagicMock()
    orch.bootstrap = AsyncMock()
    machine._orchestrator = orch
    if not hasattr(machine, "_event_queue") or machine._event_queue is None:
        machine._event_queue = asyncio.Queue()


async def _handle_event(machine: VpnStateMachine, event: VpnEvent) -> None:
    """Deliver *event* to current state; wraps sys.exit (some handlers → FailedState)."""
    with _patch_exit():
        await machine.current_state.handle(event)


# ---------------------------------------------------------------------------
# RuntimeContext
# ---------------------------------------------------------------------------


class TestRuntimeContext:
    """Tests for RuntimeContext dataclass — defaults and mutability."""

    def test_default_values(self) -> None:
        ctx = RuntimeContext()
        assert ctx.gateway is None
        assert ctx.interface is None
        assert ctx.fail_streak == 0
        assert ctx.recovery_count == 0
        assert ctx.active_server is None
        assert ctx.last_error is None
        assert ctx.target_server is None
        assert ctx.tun2socks is None
        assert ctx.singbox is None
        assert ctx.startup_time == 0.0

    def test_mutable_fields(self) -> None:
        ctx = RuntimeContext()
        ctx.gateway = "192.168.1.1"
        ctx.fail_streak = 3
        ctx.recovery_count = 2
        ctx.active_server = "barguzin"
        ctx.last_error = "timeout"
        ctx.target_server = "altay"
        assert ctx.gateway == "192.168.1.1"
        assert ctx.fail_streak == 3
        assert ctx.recovery_count == 2
        assert ctx.active_server == "barguzin"
        assert ctx.last_error == "timeout"
        assert ctx.target_server == "altay"


# ---------------------------------------------------------------------------
# VpnStateMachine construction
# ---------------------------------------------------------------------------


class TestStateMachine:
    """Tests for VpnStateMachine construction and manual transitions."""

    def test_initial_state_is_none_before_transition(self) -> None:
        machine = VpnStateMachine(BootstrappingState)
        assert machine.current_state is None

    @pytest.mark.asyncio
    async def test_enter_bootstrapping(self) -> None:
        machine = VpnStateMachine(BootstrappingState)
        _mock_orchestrator(machine)
        await machine.transition_to(BootstrappingState)
        assert isinstance(machine.current_state, BootstrappingState)


    @pytest.mark.asyncio
    async def test_enter_healthy_resets_fail_streak(self) -> None:
        machine = VpnStateMachine(HealthyState)
        await machine.transition_to(HealthyState)
        assert isinstance(machine.current_state, HealthyState)
        assert machine.context.fail_streak == 0
    @pytest.mark.asyncio
    async def test_context_shared_across_transitions(self) -> None:
        machine = VpnStateMachine(BootstrappingState)
        _mock_orchestrator(machine)
        await machine.transition_to(BootstrappingState)
        ctx = machine.context
        ctx.fail_streak = 5
        await machine.transition_to(HealthyState)
        assert machine.context.fail_streak == 0  # reset by HealthyState.on_enter
        assert machine.context is ctx


# ---------------------------------------------------------------------------
# BootstrappingState transitions
# ---------------------------------------------------------------------------


class TestBootstrappingTransitions:
    """Tests for BootstrappingState event handling."""

    @pytest.mark.asyncio
    async def test_bootstrap_done_to_healthy(self) -> None:
        machine = VpnStateMachine(BootstrappingState)
        _mock_orchestrator(machine)
        await machine.transition_to(BootstrappingState)
        await _handle_event(machine, VpnEvent(type=EventType.BOOTSTRAP_DONE))
        assert isinstance(machine.current_state, HealthyState)

    @pytest.mark.asyncio
    async def test_shutdown_requested_to_failed(self) -> None:
        machine = VpnStateMachine(BootstrappingState)
        _mock_orchestrator(machine)
        await machine.transition_to(BootstrappingState)
        await _handle_event(machine, VpnEvent(type=EventType.SHUTDOWN_REQUESTED))
        assert isinstance(machine.current_state, FailedState)
    @pytest.mark.asyncio
    async def test_timeout_to_failed(self) -> None:
        machine = VpnStateMachine(BootstrappingState)
        _mock_orchestrator(machine)
        await machine.transition_to(BootstrappingState)
        await _handle_event(machine, VpnEvent(type=EventType.TIMEOUT))
        assert isinstance(machine.current_state, FailedState)
        assert "timed out" in (machine.context.last_error or "")


# ---------------------------------------------------------------------------
# HealthyState transitions
# ---------------------------------------------------------------------------


class TestHealthyTransitions:
    """Tests for HealthyState event handling."""

    @pytest.mark.asyncio
    async def test_health_fail_to_degraded(self) -> None:
        machine = VpnStateMachine(HealthyState)
        await machine.transition_to(HealthyState)
        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_FAIL))
        assert isinstance(machine.current_state, DegradedState)
        assert machine.context.fail_streak == 1

    @pytest.mark.asyncio
    async def test_stays_on_health_ok(self) -> None:
        machine = VpnStateMachine(HealthyState)
        await machine.transition_to(HealthyState)
        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_OK))
        assert isinstance(machine.current_state, HealthyState)

    @pytest.mark.asyncio
    async def test_shutdown_requested_to_failed(self) -> None:
        machine = VpnStateMachine(HealthyState)
        await machine.transition_to(HealthyState)
        await _handle_event(machine, VpnEvent(type=EventType.SHUTDOWN_REQUESTED))
        assert isinstance(machine.current_state, FailedState)

    @pytest.mark.asyncio
    async def test_server_change_to_bootstrapping(self) -> None:
        machine = VpnStateMachine(HealthyState)
        _mock_orchestrator(machine)
        await machine.transition_to(HealthyState)
        await _handle_event(
            machine,
            VpnEvent(
                type=EventType.SERVER_CHANGE_REQUESTED,
                payload={"server_name": "altay"},
            ),
        )
        assert isinstance(machine.current_state, BootstrappingState)
        assert machine.context.target_server == "altay"

    @pytest.mark.asyncio
    async def test_restart_requested_to_restarting(self) -> None:
        machine = VpnStateMachine(HealthyState)
        await machine.transition_to(HealthyState)
        await _handle_event(machine, VpnEvent(type=EventType.RESTART_REQUESTED))
        assert isinstance(machine.current_state, RestartingState)

    @pytest.mark.asyncio
    async def test_tunnel_died_to_restarting(self) -> None:
        machine = VpnStateMachine(HealthyState)
        await machine.transition_to(HealthyState)
        await _handle_event(machine, VpnEvent(type=EventType.TUNNEL_DIED))
        assert isinstance(machine.current_state, RestartingState)


# ---------------------------------------------------------------------------
# DegradedState transitions
# ---------------------------------------------------------------------------


class TestDegradedTransitions:
    """Tests for DegradedState event handling and fail streak logic."""

    @pytest.mark.asyncio
    async def test_health_ok_to_healthy(self) -> None:
        machine = VpnStateMachine(DegradedState)
        await machine.transition_to(DegradedState)
        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_OK))
        assert isinstance(machine.current_state, HealthyState)

    @pytest.mark.asyncio
    async def test_shutdown_requested_to_failed(self) -> None:
        machine = VpnStateMachine(DegradedState)
        await machine.transition_to(DegradedState)
        await _handle_event(machine, VpnEvent(type=EventType.SHUTDOWN_REQUESTED))
        assert isinstance(machine.current_state, FailedState)

    @pytest.mark.asyncio
    async def test_tunnel_died_to_restarting(self) -> None:
        machine = VpnStateMachine(DegradedState)
        await machine.transition_to(DegradedState)
        await _handle_event(machine, VpnEvent(type=EventType.TUNNEL_DIED))
        assert isinstance(machine.current_state, RestartingState)

    @pytest.mark.asyncio
    async def test_fail_streak_below_threshold_stays(self) -> None:
        """Degraded stays Degraded when fail_streak < 3 after HEALTH_FAIL."""
        machine = VpnStateMachine(DegradedState)
        await machine.transition_to(DegradedState)
        machine.context.fail_streak = 1
        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_FAIL))
        assert isinstance(machine.current_state, DegradedState)
        assert machine.context.fail_streak == 2

    @pytest.mark.asyncio
    async def test_third_fail_to_restarting(self) -> None:
        machine = VpnStateMachine(DegradedState)
        await machine.transition_to(DegradedState)
        machine.context.fail_streak = 2
        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_FAIL))
        assert isinstance(machine.current_state, RestartingState)
        assert machine.context.fail_streak == 3

    @pytest.mark.asyncio
    async def test_fourth_fail_to_restarting(self) -> None:
        machine = VpnStateMachine(DegradedState)
        await machine.transition_to(DegradedState)
        machine.context.fail_streak = 3
        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_FAIL))
        assert isinstance(machine.current_state, RestartingState)
        assert machine.context.fail_streak == 4


# ---------------------------------------------------------------------------
# RestartingState transitions
# ---------------------------------------------------------------------------


class TestRestartingTransitions:
    """Tests for RestartingState event handling."""

    @pytest.mark.asyncio
    async def test_bootstrap_done_to_healthy(self) -> None:
        machine = VpnStateMachine(RestartingState)
        await machine.transition_to(RestartingState)
        await _handle_event(machine, VpnEvent(type=EventType.BOOTSTRAP_DONE))
        assert isinstance(machine.current_state, HealthyState)

    @pytest.mark.asyncio
    async def test_timeout_to_failed(self) -> None:
        machine = VpnStateMachine(RestartingState)
        await machine.transition_to(RestartingState)
        await _handle_event(machine, VpnEvent(type=EventType.TIMEOUT))
        assert isinstance(machine.current_state, FailedState)
        assert "timed out" in (machine.context.last_error or "")

    @pytest.mark.asyncio
    async def test_shutdown_requested_to_failed(self) -> None:
        machine = VpnStateMachine(RestartingState)
        await machine.transition_to(RestartingState)
        await _handle_event(machine, VpnEvent(type=EventType.SHUTDOWN_REQUESTED))
        assert isinstance(machine.current_state, FailedState)

    @pytest.mark.asyncio
    async def test_tunnel_died_to_failed(self) -> None:
        machine = VpnStateMachine(RestartingState)
        await machine.transition_to(RestartingState)
        await _handle_event(machine, VpnEvent(type=EventType.TUNNEL_DIED))
        assert isinstance(machine.current_state, FailedState)

    @pytest.mark.asyncio
    async def test_increments_recovery_count_on_enter(self) -> None:
        machine = VpnStateMachine(RestartingState)
        assert machine.context.recovery_count == 0
        await machine.transition_to(RestartingState)
        assert machine.context.recovery_count == 1
        await machine.transition_to(HealthyState)
        await machine.transition_to(RestartingState)
        assert machine.context.recovery_count == 2


# ---------------------------------------------------------------------------
# FailedState (terminal)
# ---------------------------------------------------------------------------


class TestFailedState:
    """Tests for FailedState — terminal, accepts no transitions."""

    @pytest.mark.asyncio
    async def test_ignores_all_events(self) -> None:
        machine = VpnStateMachine(FailedState)
        await _transition_to(machine, FailedState)
        for event_type in EventType:
            await _handle_event(machine, VpnEvent(type=event_type))
            assert isinstance(machine.current_state, FailedState)


# ---------------------------------------------------------------------------
# Fail streak integration tests
# ---------------------------------------------------------------------------


class TestFailStreak:
    """Integration-style tests for fail streak across state transitions."""

    @pytest.mark.asyncio
    async def test_accumulates_then_resets_on_healthy(self) -> None:
        """Fail streak increments through HEALTHY→DEGRADED, resets on HEALTHY re-entry."""
        machine = VpnStateMachine(HealthyState)
        await machine.transition_to(HealthyState)
        assert machine.context.fail_streak == 0

        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_FAIL))
        assert machine.context.fail_streak == 1
        assert isinstance(machine.current_state, DegradedState)

        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_OK))
        assert machine.context.fail_streak == 0
        assert isinstance(machine.current_state, HealthyState)

    @pytest.mark.asyncio
    async def test_three_consecutive_failures_triggers_restart(self) -> None:
        """Three HEALTH_FAILs in a row: Healthy→Degraded→Restarting."""
        machine = VpnStateMachine(HealthyState)
        await machine.transition_to(HealthyState)

        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_FAIL))
        assert isinstance(machine.current_state, DegradedState)
        assert machine.context.fail_streak == 1

        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_FAIL))
        assert isinstance(machine.current_state, DegradedState)
        assert machine.context.fail_streak == 2

        await _handle_event(machine, VpnEvent(type=EventType.HEALTH_FAIL))
        assert isinstance(machine.current_state, RestartingState)
        assert machine.context.fail_streak == 3


# ---------------------------------------------------------------------------
# Event queue (post)
# ---------------------------------------------------------------------------


class TestPostToQueue:
    """Tests for the async event queue (post method)."""

    @pytest.mark.asyncio
    async def test_post_enqueues_event(self) -> None:
        machine = VpnStateMachine(BootstrappingState)
        event = VpnEvent(type=EventType.HEALTH_OK)
        await machine.post(event)
        queued = machine._event_queue.get_nowait()
        assert queued is event
        assert queued.type == EventType.HEALTH_OK


# ---------------------------------------------------------------------------
# StoppedState
# ---------------------------------------------------------------------------


class TestStoppedState:
    """Tests for StoppedState — terminal stop, restart via event only."""

    @pytest.mark.asyncio
    async def test_stopped_transitions_to_bootstrapping_on_restart(self) -> None:
        """StoppedState.handle(RESTART_REQUESTED) -> BootstrappingState."""
        from unittest.mock import AsyncMock, MagicMock
        from vpn.core.state_machine.states.stopped import StoppedState

        machine = VpnStateMachine(StoppedState)
        # Mock orchestrator so BootstrappingState.on_enter() doesn't crash
        mach_orch = MagicMock()
        mach_orch.bootstrap = AsyncMock()
        machine._orchestrator = mach_orch
        machine._event_queue = asyncio.Queue()

        await machine.transition_to(StoppedState)
        assert isinstance(machine.current_state, StoppedState)

        with _patch_exit():
            await _handle_event(machine, VpnEvent(EventType.RESTART_REQUESTED))

        assert isinstance(machine.current_state, BootstrappingState)

    @pytest.mark.asyncio
    async def test_stopped_state_ignores_other_events(self) -> None:
        """StoppedState ignores events other than RESTART_REQUESTED."""
        from vpn.core.state_machine.states.stopped import StoppedState

        machine = VpnStateMachine(StoppedState)
        await machine.transition_to(StoppedState)

        with _patch_exit():
            await _handle_event(machine, VpnEvent(EventType.HEALTH_OK))
            await _handle_event(machine, VpnEvent(EventType.SINGBOX_DIED))

        assert isinstance(machine.current_state, StoppedState)


# ---------------------------------------------------------------------------
# IPC dispatch — stop / start / route
# ---------------------------------------------------------------------------


class TestIpcDispatch:
    """Tests for _dispatch() method — JSON-RPC handlers without full orchestration."""

    @pytest.fixture
    def machine(self) -> VpnStateMachine:
        """Build a machine with mocked orchestrator and shell for IPC testing."""
        from unittest.mock import MagicMock

        m = VpnStateMachine(BootstrappingState)

        orch = MagicMock()
        orch._app_cfg.table_id = 100
        orch._tun = MagicMock()
        orch._route_table = MagicMock()
        orch._nat = MagicMock()
        orch._mss = MagicMock()
        orch._sysctl_mgr = MagicMock()
        orch._subprocess = MagicMock()
        orch._tun2socks = MagicMock()
        m._orchestrator = orch

        m._shell = MagicMock()
        m._bypass_cfg = MagicMock()
        m._bypass_cfg.domains = []

        m._vpn_routes_cfg = MagicMock()
        m._vpn_routes_cfg.domains = []
        m._vpn_routes_cfg.wildcards = []
        m._vpn_routes_cfg.subnets = []

        m._dns_resolver = MagicMock()
        m._dns_resolver.resolve_ipv4.return_value = ["1.2.3.4"]

        m._rules = MagicMock()
        m.context.singbox = None
        m.context.tun2socks = None

        return m

    @pytest.mark.asyncio
    async def test_stop_enters_stopped_state(self, machine: VpnStateMachine) -> None:
        """_dispatch('stop') transitions to StoppedState and cleans up."""
        from vpn.core.state_machine.states.stopped import StoppedState

        await machine.transition_to(BootstrappingState)
        result = await machine._dispatch("stop", {})

        assert result == {"status": "stopped"}
        assert isinstance(machine.current_state, StoppedState)
        machine._orchestrator._tun.destroy.assert_called_once()
        machine._orchestrator._nat.remove.assert_called_once()
        machine._orchestrator._mss.remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_enters_bootstrapping_state(self, machine: VpnStateMachine) -> None:
        """_dispatch('start') transitions to BootstrappingState after mini-cleanup."""
        await machine.transition_to(BootstrappingState)
        result = await machine._dispatch("start", {})

        assert result == {"status": "starting"}
        assert isinstance(machine.current_state, BootstrappingState)
        machine._shell.run.assert_any_call("ip link del tun0 2>/dev/null || true")

    @pytest.mark.asyncio
    async def test_route_add_domain(self, machine: VpnStateMachine) -> None:
        """_dispatch('route.add', domain) resolves IPs and adds routes."""
        result = await machine._dispatch("route.add", {"domain": "api.github.com"})

        assert result["domain"] == "api.github.com"
        assert result["ips"] == ["1.2.3.4"]
        machine._shell.run.assert_any_call(
            "ip route add 1.2.3.4 dev tun0 table 100 2>/dev/null || true"
        )
        assert "api.github.com" in machine._vpn_routes_cfg.domains
        assert machine.context.route_ips["api.github.com"] == ["1.2.3.4"]

    @pytest.mark.asyncio
    async def test_route_add_wildcard(self, machine: VpnStateMachine) -> None:
        """_dispatch('route.add', wildcard) stores for next restart."""
        result = await machine._dispatch("route.add", {"wildcard": "*.openai.com"})
        assert result == {"wildcard": "*.openai.com", "applied": False, "note": "takes effect on next restart"}
        assert "*.openai.com" in machine._vpn_routes_cfg.wildcards

    @pytest.mark.asyncio
    async def test_route_add_subnet(self, machine: VpnStateMachine) -> None:
        """_dispatch('route.add', subnet) adds ip route immediately."""
        result = await machine._dispatch("route.add", {"subnet": "10.0.0.0/8"})
        assert result == {"subnet": "10.0.0.0/8"}
        machine._shell.run.assert_any_call("ip route add 10.0.0.0/8 dev tun0 table 100 2>/dev/null || true")

    @pytest.mark.asyncio
    async def test_route_remove_wildcard(self, machine: VpnStateMachine) -> None:
        """_dispatch('route.remove', wildcard) drops from config."""
        machine._vpn_routes_cfg.wildcards = ["*.openai.com"]
        result = await machine._dispatch("route.remove", {"wildcard": "*.openai.com"})
        assert result == {"wildcard": "*.openai.com"}

    @pytest.mark.asyncio
    async def test_route_remove_subnet(self, machine: VpnStateMachine) -> None:
        """_dispatch('route.remove', subnet) deletes ip route."""
        machine._vpn_routes_cfg.subnets = ["10.0.0.0/8"]
        result = await machine._dispatch("route.remove", {"subnet": "10.0.0.0/8"})
        assert result == {"subnet": "10.0.0.0/8"}
        machine._shell.run.assert_any_call("ip route del 10.0.0.0/8 table 100 2>/dev/null || true")

    @pytest.mark.asyncio
    async def test_route_list(self, machine: VpnStateMachine) -> None:
        """_dispatch('route.list') returns current state."""
        machine._vpn_routes_cfg.domains = ["api.github.com"]
        machine._vpn_routes_cfg.wildcards = ["*.openai.com"]
        machine._vpn_routes_cfg.subnets = ["10.0.0.0/8"]
        result = await machine._dispatch("route.list", {})
        assert result["domains"] == ["api.github.com"]
        assert result["wildcards"] == ["*.openai.com"]
        assert result["subnets"] == ["10.0.0.0/8"]

    @pytest.mark.asyncio
    async def test_restart_posts_event(self, machine: VpnStateMachine) -> None:
        """_dispatch('restart') posts RESTART_REQUESTED and returns status."""
        result = await machine._dispatch("restart", {})
        assert result == {"status": "restarting"}

    @pytest.mark.asyncio
    async def test_status_returns_context(self, machine: VpnStateMachine) -> None:
        """_dispatch('status') returns gateway, interface, tun2socks state."""
        machine.context.gateway = "10.0.0.1"
        machine.context.interface = "eth0"
        result = await machine._dispatch("status", {})
        assert result["gateway"] == "10.0.0.1"
        assert result["interface"] == "eth0"

    @pytest.mark.asyncio
    async def test_bypass_add_list_remove(self, machine: VpnStateMachine) -> None:
        """_dispatch('bypass.add/list/remove') manages bypass domains."""
        await machine._dispatch("bypass.add", {"domain": "example.com"})
        result = await machine._dispatch("bypass.list", {})
        assert "example.com" in result
        await machine._dispatch("bypass.remove", {"domain": "example.com"})
        result = await machine._dispatch("bypass.list", {})
        assert "example.com" not in result

    @pytest.mark.asyncio
    async def test_unknown_method_raises(self, machine: VpnStateMachine) -> None:
        """_dispatch raises ValueError for unknown method."""
        with pytest.raises(ValueError, match="Unknown method"):
            await machine._dispatch("nonexistent", {})

    @pytest.mark.asyncio
    async def test_route_remove_domain(self, machine: VpnStateMachine) -> None:
        """_dispatch('route.remove', domain) deletes routes and cleans state."""
        machine._vpn_routes_cfg.domains = ["api.github.com"]
        machine.context.route_ips = {"api.github.com": ["1.2.3.4"]}

        result = await machine._dispatch("route.remove", {"domain": "api.github.com"})

        assert result == {"domain": "api.github.com"}
        machine._shell.run.assert_any_call(
            "ip route del 1.2.3.4 table 100 2>/dev/null || true"
        )
        assert "api.github.com" not in machine._vpn_routes_cfg.domains
        assert "api.github.com" not in machine.context.route_ips

    @pytest.mark.asyncio
    async def test_server_list_and_current(self, machine: VpnStateMachine) -> None:
        """_dispatch('server.list/current') returns mocked data."""
        from unittest.mock import MagicMock
        from vpn.core.ports import ServerInfo

        mock_provider = MagicMock()
        mock_provider.list_servers.return_value = [
            ServerInfo(name="test", tag="tag", country="ru", host="1.2.3.4", port=443)
        ]
        machine._provider = mock_provider
        machine.context.active_server = "test"

        result = await machine._dispatch("server.list", {})
        assert len(result) == 1
        assert result[0]["name"] == "test"

        result = await machine._dispatch("server.current", {})
        assert result == {"server": "test"}
