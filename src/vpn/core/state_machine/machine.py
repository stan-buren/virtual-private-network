"""Event-driven state machine engine for the VPN daemon.

The state machine consumes events from an asyncio.Queue and delegates to the
current state's handle() method. Event emitters (process watchers, health
checker, CLI handler) push events into the queue.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Type

from vpn.core.events import VpnEvent
from vpn.core.state_machine.context import RuntimeContext
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")


class VpnStateMachine:
    """Event-driven finite state machine for VPN lifecycle management.

    Attributes:
        context: Mutable runtime state shared across all states.
        current_state: The currently active state instance.
    """

    def __init__(self, initial_state_cls: Type[VpnState]) -> None:
        """Initialise the state machine with a starting state class.

        Args:
            initial_state_cls: The state class to enter on startup.
        """
        self.context = RuntimeContext()
        self._event_queue: asyncio.Queue[VpnEvent] = asyncio.Queue()
        self._current_state: VpnState | None = None
        self._initial_state_cls = initial_state_cls
        self._running = False

    @property
    def current_state(self) -> VpnState | None:
        """The currently active state instance, or None before startup."""
        return self._current_state

    async def post(self, event: VpnEvent) -> None:
        """Push an event into the queue for asynchronous processing.

        Args:
            event: The event to enqueue.
        """
        await self._event_queue.put(event)
        logger.debug("Event posted: %s", event.type.name)

    async def transition_to(self, state_cls: Type[VpnState]) -> None:
        """Execute a state transition: exit current, enter new.

        Calls on_exit() on the current state (if any), then instantiates
        and enters the target state. Logs the transition at DEBUG level
        for the exit and INFO for the entry.

        Args:
            state_cls: The target state class.
        """
        if self._current_state is not None:
            await self._current_state.on_exit()
            logger.debug(
                "Exited state: %s", type(self._current_state).__name__
            )
        self._current_state = state_cls(self)
        logger.info("Transitioned to: %s", state_cls.__name__)
        await self._current_state.on_enter()

    async def run(self) -> None:
        """Start the event loop.  Blocks until :meth:`stop` is called.

        Enters the initial state, then processes events from the queue
        indefinitely.  Each event is dispatched to the current state's
        :meth:`~VpnState.handle` method.

        Raises:
            asyncio.CancelledError: Propagated upward so the caller can
                perform cleanup.
        """
        self._running = True
        await self.transition_to(self._initial_state_cls)
        logger.info("State machine running")

        while self._running:
            try:
                event = await self._event_queue.get()
                logger.debug("Processing event: %s", event.type.name)
                if self._current_state is not None:
                    await self._current_state.handle(event)
            except asyncio.CancelledError:
                logger.info("State machine cancelled")
                raise
            except Exception:
                logger.exception("Unhandled error in state machine loop")

    def stop(self) -> None:
        """Signal the event loop to stop processing.

        The :meth:`run` loop will finish the current event and then
        exit cleanly on the next iteration.
        """
        self._running = False
