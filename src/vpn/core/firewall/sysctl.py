"""sysctl management — IP forwarding, IPv6 configuration."""

from __future__ import annotations

import logging

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")


class SysctlManager:
    """Manages kernel network parameters via sysctl."""

    def __init__(self, shell: ShellPort):
        self._shell = shell

    def enable_ip_forward(self) -> None:
        """Enable IPv4 packet forwarding."""
        self._shell.run("sysctl -w net.ipv4.ip_forward=1 >/dev/null")
        logger.info("IPv4 forwarding enabled")

    def disable_ipv6_wan(self) -> None:
        """Disable IPv6 on all interfaces except loopback.

        sing-box binds SOCKS5 on [::1]:3066, so loopback IPv6 must stay enabled.
        """
        self._shell.run("sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null")
        self._shell.run("sysctl -w net.ipv6.conf.lo.disable_ipv6=0 >/dev/null")
        logger.info("IPv6 disabled on WAN, preserved on loopback")

    def restore_ipv6(self) -> None:
        """Re-enable IPv6 on all interfaces."""
        self._shell.run("sysctl -w net.ipv6.conf.all.disable_ipv6=0 >/dev/null")
        logger.info("IPv6 restored on all interfaces")
