"""Route table management — batch route injection, default gateway."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")


@dataclass(frozen=True)
class RouteEntry:
    """A single routing table entry.

    Attributes:
        subnet: CIDR subnet to route.
        via: Gateway IP for non-VPN routes.
        dev: Device name ('tun0' for VPN, physical interface for bypass).
        table_id: Linux routing table ID.
    """

    subnet: str
    via: str | None
    dev: str
    table_id: str


class RouteTable:
    """Manages routing table entries using ip route batch operations."""

    def __init__(self, shell: ShellPort):
        self._shell = shell

    def load_batch(self, entries: list[RouteEntry], table_id: str) -> int:
        """Write route entries to a temp file and apply via 'ip -force -batch'.

        Args:
            entries: List of RouteEntry objects to apply.
            table_id: Routing table ID (e.g. '100').

        Returns:
            The number of routes applied.
        """
        if not entries:
            logger.info("No routes to apply")
            return 0

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, prefix="vpn_routes_"
        ) as f:
            batch_path = f.name
            for entry in entries:
                line = "route add %s" % entry.subnet
                if entry.via:
                    line += " via %s" % entry.via
                line += " dev %s table %s" % (entry.dev, table_id)
                f.write(line + "\n")

        try:
            result = self._shell.run(
                "ip -force -batch %s 2>/dev/null" % batch_path
            )
            count = len(entries)
            logger.info("Batch injected %d routes into table %s", count, table_id)
            return count
        finally:
            if os.path.exists(batch_path):
                os.remove(batch_path)

    def set_default(self, table_id: str) -> None:
        """Set the default route for a routing table to tun0."""
        self._shell.run(
            "ip route add default dev tun0 table %s 2>/dev/null || true" % table_id
        )
        logger.info("Default route set: table %s -> tun0", table_id)

    def flush(self, table_id: str) -> None:
        """Remove all routes from a routing table."""
        self._shell.run(
            "ip route flush table %s 2>/dev/null || true" % table_id
        )
        logger.info("Table %s flushed", table_id)
