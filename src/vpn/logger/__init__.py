"""VPN Daemon Observability and Logging Domain.

Exposes centralized logger configurations and domain exception hierarchies.
"""

from __future__ import annotations

from vpn.logger.exceptions import (
    VpnConfigError,
    VpnConnectionError,
    VpnError,
    VpnHealthError,
    VpnTunnelError,
)
from vpn.logger.logger_config import setup_logging

__all__ = [
    "VpnConfigError",
    "VpnConnectionError",
    "VpnError",
    "VpnHealthError",
    "VpnTunnelError",
    "setup_logging",
]
