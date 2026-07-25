"""VPN Daemon Custom Exception Hierarchy."""

from __future__ import annotations


class VpnError(Exception):
    """Base exception for all VPN daemon operational failures."""


class VpnConfigError(VpnError):
    """Raised when configuration files are missing, malformed, or invalid."""


class VpnConnectionError(VpnError):
    """Raised when network operations, tunnel connections, or endpoints fail."""


class VpnTunnelError(VpnError):
    """Raised when tun2socks or sing-box process failures occur."""


class VpnHealthError(VpnError):
    """Raised when health checks exhaust retries and recovery fails."""
