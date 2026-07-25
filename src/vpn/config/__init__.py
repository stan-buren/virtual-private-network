"""Configuration management subpackage."""

from __future__ import annotations

from vpn.config.config_loader import (
    get_app_config,
    get_bypass_config,
    get_health_config,
    get_network_config,
    get_notification_config,
    get_servers_config,
    get_tunnel_config,
    get_vpn_routes_config,
)
from vpn.config.paths import PROJECT_ROOT, load_paths_config

__all__ = [
    "PROJECT_ROOT",
    "get_app_config",
    "get_bypass_config",
    "get_health_config",
    "get_network_config",
    "get_notification_config",
    "get_servers_config",
    "get_tunnel_config",
    "get_vpn_routes_config",
    "load_paths_config",
]
