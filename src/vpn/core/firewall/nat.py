"""iptables NAT management — POSTROUTING MASQUERADE rules."""

from __future__ import annotations

import logging

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")


class NatManager:
    """Manages iptables NAT rules for VPN traffic masquerading."""

    def __init__(self, shell: ShellPort, chain_name: str = "VPN_ASUS_OUTPUT"):
        self._shell = shell
        self._chain_name = chain_name

    def apply(self, wan_interface: str) -> None:
        """Create the NAT chain, add MASQUERADE rules, hook into POSTROUTING.

        Args:
            wan_interface: Name of the WAN physical interface.
        """
        self._shell.run(
            "iptables -t nat -N %s 2>/dev/null || true" % self._chain_name
        )
        self._shell.run("iptables -t nat -F %s" % self._chain_name)
        self._shell.run(
            "iptables -t nat -A %s -o tun0 -j MASQUERADE" % self._chain_name
        )
        self._shell.run(
            "iptables -t nat -A %s -o %s -j MASQUERADE" % (self._chain_name, wan_interface)
        )

        result = self._shell.run("iptables -t nat -S POSTROUTING", capture=True)
        current = result.stdout if result else ""
        if self._chain_name not in current:
            self._shell.run(
                "iptables -t nat -I POSTROUTING 1 -j %s" % self._chain_name
            )
        logger.info("NAT rules applied for chain %s", self._chain_name)

    def remove(self) -> None:
        """Remove the NAT chain and its POSTROUTING hook."""
        self._shell.run(
            "iptables -t nat -D POSTROUTING -j %s 2>/dev/null || true" % self._chain_name
        )
        self._shell.run(
            "iptables -t nat -F %s 2>/dev/null || true" % self._chain_name
        )
        self._shell.run(
            "iptables -t nat -X %s 2>/dev/null || true" % self._chain_name
        )
        logger.info("NAT rules removed for chain %s", self._chain_name)
