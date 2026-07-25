"""TUN interface lifecycle management."""

from __future__ import annotations

import logging

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")


class TunInterface:
    """Manages the tun0 virtual network interface for tun2socks bridging."""

    def __init__(self, shell: ShellPort, address: str = "198.18.0.1/15", mtu: int = 1360):
        self._shell = shell
        self._address = address
        self._mtu = mtu

    def create(self) -> None:
        """Create and bring up the tun0 interface."""
        self._shell.run("ip tuntap add mode tun dev tun0 2>/dev/null || true")
        self._shell.run("ip addr add %s dev tun0 2>/dev/null || true" % self._address)
        self._shell.run("ip link set dev tun0 mtu %d up" % self._mtu)
        logger.info(
            "tun0 created: address=%s, mtu=%d",
            self._address,
            self._mtu,
        )

    def destroy(self) -> None:
        """Bring down and remove the tun0 interface."""
        self._shell.run("ip link set dev tun0 down 2>/dev/null || true")
        self._shell.run("ip tuntap del mode tun dev tun0 2>/dev/null || true")
        logger.info("tun0 destroyed")
