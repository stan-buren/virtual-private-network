"""Routing rule manager — ip rule priority constants and rule lifecycle."""

from __future__ import annotations

import logging

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")

# Priority constants: lower number = higher priority.
# DNS rules (3-6) MUST be below 8 to avoid WireGuard interception.
PRIO_SERVER_IPS = 1
PRIO_DNS_START = 3
PRIO_DNS_END = 6
PRIO_LAN_START = 10
PRIO_LAN_END = 12
PRIO_TORRENT = 20
PRIO_CATCHALL = 30


class RuleManager:
    """Manages ip rule entries for selective routing.

    Maintains the priority schema that ensures DNS bypasses work even
    when WireGuard (priorities 8-9) is active on the host.
    """

    def __init__(self, shell: ShellPort):
        self._shell = shell

    def add_server_bypass(self, ip: str) -> None:
        """Route a specific server IP through table main (bypass VPN).

        Used for the VLESS server itself to prevent routing loops.
        """
        self._shell.run(
            "ip rule del to %s 2>/dev/null || true" % ip
        )
        self._shell.run(
            "ip rule add to %s table main priority %d" % (ip, PRIO_SERVER_IPS)
        )
        logger.info("Server bypass: %s -> table main (priority %d)", ip, PRIO_SERVER_IPS)

    def add_dns_bypass(self, ip: str, priority: int) -> None:
        """Route a DNS server through table main."""
        self._shell.run("ip rule del to %s 2>/dev/null || true" % ip)
        self._shell.run(
            "ip rule add to %s table main priority %d" % (ip, priority)
        )
        logger.info("DNS bypass: %s -> table main (priority %d)", ip, priority)

    def add_lan_bypass(self, subnet: str, priority: int) -> None:
        """Route a LAN subnet through table main."""
        self._shell.run(
            "ip rule add to %s table main priority %d 2>/dev/null || true" % (subnet, priority)
        )
        logger.info("LAN bypass: %s -> table main (priority %d)", subnet, priority)

    def add_torrent_bypass(self) -> None:
        """Route fwmark 1 traffic (MAM torrent) through table main."""
        self._shell.run(
            "ip rule del fwmark 1 table main priority %d 2>/dev/null || true" % PRIO_TORRENT
        )
        self._shell.run(
            "ip rule add fwmark 1 table main priority %d" % PRIO_TORRENT
        )
        logger.info("Torrent bypass: fwmark 1 -> table main (priority %d)", PRIO_TORRENT)

    def add_catchall(self, table_id: str) -> None:
        """Add catch-all rule routing all remaining traffic into the VPN table."""
        self._shell.run(
            "ip rule add from all table %s priority %d 2>/dev/null || true" % (table_id, PRIO_CATCHALL)
        )
        logger.info("Catch-all: all traffic -> table %s (priority %d)", table_id, PRIO_CATCHALL)

    def clear_all(self) -> None:
        """Remove all known priority rules (1-30), handling duplicates.

        Uses while-loop for EVERY priority — a single ``ip rule del`` only
        removes one rule.  After a crash-loop there may be multiple rules
        at the same priority (duplicates from repeated bootstrap attempts).
        """
        for p in range(1, 31):
            self._shell.run(
                "while ip rule del priority %d 2>/dev/null; do :; done" % p
            )
        logger.info("All ip rules cleared (priorities 1-30)")

    def clear_server_bypasses(self) -> None:
        """Remove only priority 1 rules (server IP bypasses)."""
        self._shell.run("while ip rule del priority 1 2>/dev/null; do :; done")
        logger.info("Server bypass rules cleared")
