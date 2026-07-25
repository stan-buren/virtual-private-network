"""Tests for state machine — transitions, timeouts, fail streak."""

from __future__ import annotations

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
        await machine.transition_to(BootstrappingState)
        await _handle_event(machine, VpnEvent(type=EventType.BOOTSTRAP_DONE))
        assert isinstance(machine.current_state, HealthyState)

    @pytest.mark.asyncio
    async def test_shutdown_requested_to_failed(self) -> None:
        machine = VpnStateMachine(BootstrappingState)
        await machine.transition_to(BootstrappingState)
        await _handle_event(machine, VpnEvent(type=EventType.SHUTDOWN_REQUESTED))
        assert isinstance(machine.current_state, FailedState)

    @pytest.mark.asyncio
    async def test_timeout_to_failed(self) -> None:
        machine = VpnStateMachine(BootstrappingState)
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
