"""TCP MSS clamping for VPN tunnel traffic."""

from __future__ import annotations

import logging

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")


class MssClamp:
    """Sets TCP MSS clamping to prevent packet fragmentation on the VPN tunnel."""

    def __init__(self, shell: ShellPort, mss_value: int = 1360):
        self._shell = shell
        self._mss_value = mss_value

    def apply(self) -> None:
        """Add the TCPMSS rule to mangle FORWARD chain."""
        self._shell.run(
            "iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN "
            "-j TCPMSS --set-mss %d 2>/dev/null || true" % self._mss_value
        )
        logger.info("MSS clamping applied: %d", self._mss_value)

    def remove(self) -> None:
        """Remove the TCPMSS rule from mangle FORWARD chain."""
        self._shell.run(
            "iptables -t mangle -D FORWARD -p tcp --tcp-flags SYN,RST SYN "
            "-j TCPMSS --set-mss %d 2>/dev/null || true" % self._mss_value
        )
        logger.info("MSS clamping removed")
