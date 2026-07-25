"""Configuration loader facade for the VPN daemon.

Provides cached singleton access to all configuration objects. Follows the
composed master config pattern: get_config() loads all sub-configs once, and
granular getters delegate to it without redundant parsing.
"""

from __future__ import annotations

from functools import cache

from vpn.config.core.app import AppConfig
from vpn.config.core.bypass import BypassConfig
from vpn.config.core.health import HealthConfig
from vpn.config.core.network import NetworkConfig
from vpn.config.core.notification import NotificationConfig
from vpn.config.core.servers import ServersConfig
from vpn.config.core.tunnel import TunnelConfig
from vpn.config.core.vpn_routes import VpnRoutesConfig


@cache
def get_app_config() -> AppConfig:
    """Loads and returns the cached AppConfig singleton."""
    return AppConfig._from_yaml()


@cache
def get_network_config() -> NetworkConfig:
    """Loads and returns the cached NetworkConfig singleton."""
    return NetworkConfig._from_yaml()


@cache
def get_health_config() -> HealthConfig:
    """Loads and returns the cached HealthConfig singleton."""
    return HealthConfig._from_yaml()


@cache
def get_tunnel_config() -> TunnelConfig:
    """Loads and returns the cached TunnelConfig singleton."""
    return TunnelConfig._from_yaml()


@cache
def get_notification_config() -> NotificationConfig:
    """Loads and returns the cached NotificationConfig singleton."""
    return NotificationConfig._from_yaml()


@cache
def get_servers_config() -> ServersConfig:
    """Loads and returns the cached ServersConfig singleton."""
    return ServersConfig._from_yaml()


@cache
def get_bypass_config() -> BypassConfig:
    """Loads and returns the cached BypassConfig singleton."""
    return BypassConfig._from_yaml()


@cache
def get_vpn_routes_config() -> VpnRoutesConfig:
    """Loads and returns the cached VpnRoutesConfig singleton."""
    return VpnRoutesConfig._from_yaml()
