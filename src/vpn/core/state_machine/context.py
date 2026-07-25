"""Shared runtime context for the state machine.

Holds mutable state shared across state transitions: gateway, interface,
process handles, failure counters, and the active server name.
"""

from __future__ import annotations

from dataclasses import dataclass

from vpn.core.ports import PopenHandle


@dataclass
class RuntimeContext:
    """Mutable runtime state shared by all state machine states.

    Attributes:
        gateway: Default IPv4 gateway IP address.
        interface: Physical network interface name.
        tun2socks: Handle for the tun2socks subprocess.
        singbox: Handle for the sing-box subprocess.
        fail_streak: Consecutive health check failures.
        recovery_count: Total recovery cycles since startup.
        startup_time: Unix timestamp of daemon start.
        active_server: Name of the currently active VPN server.
        last_error: Error message from the most recent failure.
        target_server: Pending server name for CLI-triggered switch.
    """

    gateway: str | None = None
    interface: str | None = None
    tun2socks: PopenHandle | None = None
    singbox: PopenHandle | None = None
    fail_streak: int = 0
    recovery_count: int = 0
    startup_time: float = 0.0
    active_server: str | None = None
    last_error: str | None = None
    target_server: str | None = None
