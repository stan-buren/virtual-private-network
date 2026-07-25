"""Abstract base class for VPN state machine states."""

from __future__ import annotations

import abc

from vpn.core.events import VpnEvent


class VpnState(abc.ABC):
    """Abstract base for all VPN daemon states.

    Each concrete state implements on_enter, on_exit, and handle.
    States receive a reference to the machine for transition_to() calls.
    """

    def __init__(self, machine: VpnStateMachine) -> None:
        self._machine = machine

    @property
    def machine(self) -> VpnStateMachine:
        return self._machine

    @property
    def ctx(self):
        return self._machine.context

    @abc.abstractmethod
    async def on_enter(self) -> None:
        """Called when the state machine transitions into this state."""
        ...

    @abc.abstractmethod
    async def on_exit(self) -> None:
        """Called when the state machine transitions out of this state."""
        ...

    @abc.abstractmethod
    async def handle(self, event: VpnEvent) -> None:
        """Process an incoming event from the event queue.

        Args:
            event: The event to process.
        """
        ...

    async def transition_to(self, state_cls: type[VpnState]) -> None:
        """Request a transition to a new state.

        Args:
            state_cls: The target state class to transition to.
        """
        await self._machine.transition_to(state_cls)
