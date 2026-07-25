"""Akonit provider adapter — implements VpnProviderPort for Akonit VLESS Reality keys."""

from __future__ import annotations

import json
import logging
from typing import Any

from vpn.config.config_loader import get_servers_config
from vpn.core.ports import ServerInfo, VpnProviderPort

logger = logging.getLogger("vpn")

SINGBOX_TEMPLATE: dict[str, Any] = {
    "log": {"level": "info", "timestamp": True},
    "inbounds": [
        {
            "type": "mixed",
            "tag": "mixed-in",
            "listen": "0.0.0.0",
            "listen_port": 12334,
            "sniff": True,
            "sniff_override_destination": True,
        }
    ],
    "outbounds": [
        {"type": "direct", "tag": "direct-out"},
    ],
    "route": {
        "rules": [
            {"protocol": "dns", "action": "hijack-dns"},
            {"ip_is_private": True, "outbound": "direct-out"},
        ],
        "final": "vless-out",
        "auto_detect_interface": True,
    },
    "dns": {
        "servers": [
            {
                "tag": "dns-remote",
                "address": "https://1.1.1.1/dns-query",
                "detour": "vless-out",
            },
            {
                "tag": "dns-local",
                "address": "8.8.8.8",
                "detour": "direct-out",
            },
        ],
        "rules": [
            {"outbound": "any", "server": "dns-local"},
            {"query_type": ["A", "AAAA"], "server": "dns-remote"},
        ],
        "strategy": "ipv4_only",
    },
}


class AkonitProvider:
    """Implements VpnProviderPort for Akonit VLESS Reality keys.

    Reads server info from a sing-box profile JSON (data/profile_keys_akonit_*.json)
    and the server registry (config/servers.yaml).  Matches CLI-friendly names from the
    registry to outbound entries in the profile by substring-matching the provider tag.
    """

    def __init__(self, profile_path: str) -> None:
        """Initialise the provider with the path to the sing-box profile JSON.

        Args:
            profile_path: Absolute or relative path to the profile JSON file.
        """
        self._profile_path = profile_path
        self._servers_config = get_servers_config()
        self._profile_data: dict[str, Any] | None = None

    def _load_profile(self) -> dict[str, Any]:
        """Lazily load and cache the profile JSON from disk."""
        if self._profile_data is None:
            with open(self._profile_path, encoding="utf-8") as f:
                self._profile_data = json.load(f)
        return self._profile_data

    def _find_outbound(self, tag_substring: str) -> dict[str, Any] | None:
        """Return the first outbound whose ``tag`` contains *tag_substring*.

        Args:
            tag_substring: The provider tag (from servers.yaml) to match against
                outbound ``"tag"`` fields.  Matching is case-sensitive substring.

        Returns:
            The matching outbound dict, or ``None`` if no outbound matches.
        """
        profile = self._load_profile()
        for outbound in profile.get("outbounds", []):
            obj_tag: str = outbound.get("tag", "")
            if tag_substring in obj_tag:
                return outbound
        return None

    # ------------------------------------------------------------------ VpnProviderPort

    def list_servers(self) -> list[ServerInfo]:
        """Return every server present in both the registry and the profile JSON.

        Returns:
            A list of :class:`ServerInfo` entries, one per registered server that
            has a matching outbound in the profile.
        """
        result: list[ServerInfo] = []
        for name, entry in self._servers_config.servers.items():
            outbound = self._find_outbound(entry.tag)
            if outbound is not None:
                result.append(
                    ServerInfo(
                        name=name,
                        tag=outbound.get("tag", entry.tag),
                        country=entry.country,
                        host=outbound.get("server", "unknown"),
                        port=outbound.get("server_port", 443),
                    )
                )
        return result

    def get_server(self, name: str) -> ServerInfo:
        """Return metadata for a single server by its CLI name.

        Args:
            name: Short CLI name (e.g. ``"barguzin"``).

        Returns:
            A :class:`ServerInfo` for the requested server.

        Raises:
            KeyError: If *name* is unknown or the matching outbound is missing
                from the profile.
        """
        entry = self._servers_config.servers[name]
        outbound = self._find_outbound(entry.tag)
        if outbound is None:
            raise KeyError(
                "Server '%s' (tag: '%s') not found in profile" % (name, entry.tag)
            )
        return ServerInfo(
            name=name,
            tag=outbound.get("tag", entry.tag),
            country=entry.country,
            host=outbound.get("server", "unknown"),
            port=outbound.get("server_port", 443),
        )

    def build_singbox_config(self, server_name: str) -> str:
        """Assemble a complete sing-box ``config.json`` for *server_name*.

        Takes the :attr:`SINGBOX_TEMPLATE`, inserts the VLESS Reality outbound
        from the profile as the active outbound (tagged ``"vless-out"``), and
        returns the resulting JSON string.

        Args:
            server_name: Short CLI name of the target server.

        Returns:
            Pretty-printed (indent 2) JSON string ready to write to disk.

        Raises:
            KeyError: If *server_name* is unknown or its outbound is not found.
        """
        server = self.get_server(server_name)
        outbound = self._find_outbound(self._servers_config.servers[server_name].tag)
        if outbound is None:
            raise KeyError("Outbound not found for server: %s" % server_name)

        # Clone so we don't mutate the cached profile data.
        outbound_copy = dict(outbound)
        outbound_copy["tag"] = "vless-out"

        config: dict[str, Any] = json.loads(json.dumps(SINGBOX_TEMPLATE))
        config["outbounds"].insert(0, outbound_copy)

        return json.dumps(config, indent=2)

    def sanitize_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Remove or rewrite sing-box fields unsupported by the current runtime.

        The profile JSON may contain fields (e.g. ``experimental.statistics``,
        batch DNS servers, ``"default"`` on selectors, remote rule-set ``"path"``)
        that older sing-box releases reject.  This method cleans them in-place.

        Args:
            raw: The raw dict parsed from the profile JSON.

        Returns:
            The sanitised dict (same object, mutated).
        """
        # Remove experimental.statistics
        experimental: dict[str, Any] = raw.get("experimental", {})
        if "statistics" in experimental:
            del experimental["statistics"]
            logger.info("Sanitized: removed experimental.statistics")

        # Sanitize DNS servers
        dns: dict[str, Any] = raw.get("dns", {})
        servers: list[dict[str, Any]] = dns.get("servers", [])
        new_servers: list[dict[str, Any]] = []
        for srv in servers:
            srv_type: str | None = srv.get("type")
            if srv_type == "predefined":
                tag: str = srv.get("tag", "unknown")
                logger.info("Sanitized: removed predefined DNS %s", tag)
                continue
            if srv_type == "batch":
                tag = srv.get("tag", "unknown")
                if tag == "dns_proxy_out":
                    srv = {
                        "tag": tag,
                        "type": "udp",
                        "server": "8.8.8.8",
                        "server_port": 53,
                    }
                else:
                    srv = {"tag": tag, "type": "local"}
                logger.info("Sanitized: converted batch DNS %s", tag)
            new_servers.append(srv)
        dns["servers"] = new_servers

        # Remove unsupported 'name' fields from rules
        for rule in dns.get("rules", []):
            rule.pop("name", None)
        for rule in raw.get("route", {}).get("rules", []):
            rule.pop("name", None)

        # Remove unsupported 'default' from urltest/selector outbounds
        for outbound in raw.get("outbounds", []):
            out_type: str | None = outbound.get("type")
            if out_type in ("urltest", "selector", "url-test"):
                outbound.pop("default", None)

        # Remove unsupported 'path' from remote rule_sets
        for rset in raw.get("route", {}).get("rule_set", []):
            if rset.get("type") == "remote":
                rset.pop("path", None)

        return raw
