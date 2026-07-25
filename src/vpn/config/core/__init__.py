"""Configuration core classes and schemas package."""

from __future__ import annotations

from vpn.config.core.app import AppConfig
from vpn.config.core.bypass import BypassConfig
from vpn.config.core.health import HealthConfig
from vpn.config.core.network import NetworkConfig
from vpn.config.core.notification import NotificationConfig
from vpn.config.core.servers import ServerEntry, ServersConfig
from vpn.config.core.tunnel import TunnelConfig
from vpn.config.core.vpn_routes import VpnRoutesConfig

__all__ = [
    "AppConfig",
    "BypassConfig",
    "HealthConfig",
    "NetworkConfig",
    "NotificationConfig",
    "ServerEntry",
    "ServersConfig",
    "TunnelConfig",
    "VpnRoutesConfig",
]
