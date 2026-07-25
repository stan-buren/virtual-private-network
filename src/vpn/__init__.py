"""VPN Orchestrator — event-driven sing-box manager with tun2socks bridging.

Core & Adapters hexagonal architecture. Provider-agnostic core with pluggable
VPN provider adapters.
"""

from __future__ import annotations

from vpn.config import PROJECT_ROOT
from vpn.logger import (
    VpnConfigError,
    VpnConnectionError,
    VpnError,
    VpnHealthError,
    VpnTunnelError,
    setup_logging,
)

__all__ = [
    "PROJECT_ROOT",
    "VpnConfigError",
    "VpnConnectionError",
    "VpnError",
    "VpnHealthError",
    "VpnTunnelError",
    "setup_logging",
]
