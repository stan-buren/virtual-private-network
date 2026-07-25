"""Akonit provider adapter — implements VpnProviderPort for Akonit VLESS Reality keys."""

from __future__ import annotations

import json
import re
import logging
from typing import Any

from vpn.config.config_loader import get_servers_config
from vpn.core.ports import ServerInfo, VpnProviderPort

logger = logging.getLogger("vpn")

_EMOJI_RE = re.compile(
    "[\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U00002600-\U000027BF"
    "\U0000200D\U0000FE0F"
    "\U000000A9\U000000AE"
    "\u2800-\u28FF"
    "]+"
)



class AkonitProvider:
    """Implements VpnProviderPort for Akonit VLESS Reality keys.

    Reads server info from a sing-box profile JSON (data/profile_keys_akonit_*.json)
    and the server registry (config/servers.yaml).  Matches CLI-friendly names from the
    registry to outbound entries in the profile by substring-matching the provider tag.
    """

    @staticmethod
    def _normalize_tag(tag: str) -> str:
        """Strip emoji, '(Без рекламы)', and collapse whitespace from a tag."""
        tag = _EMOJI_RE.sub("", tag)
        tag = tag.replace("(Без рекламы)", "")
        return " ".join(tag.split()).strip()

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

        Both sides are normalized (emoji stripped) before comparison.

        Args:
            tag_substring: The provider tag (from servers.yaml) to match against
                outbound ``"tag"`` fields.

        Returns:
            The matching outbound dict, or ``None`` if no outbound matches.
        """
        norm_sub = self._normalize_tag(tag_substring)
        profile = self._load_profile()
        for outbound in profile.get("outbounds", []):
            if norm_sub in self._normalize_tag(outbound.get("tag", "")):
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
        """Return a sing-box config.json with *server_name* as the active outbound.

        Loads the provider profile (SSOT), sets ``urltest_out.default`` to the
        matching outbound tag, sanitizes, and returns the JSON string.

        Args:
            server_name: Short CLI name of the target server (e.g. 'barguzin').

        Returns:
            Pretty-printed JSON string with the selected server active.

        Raises:
            KeyError: If *server_name* is unknown.
        """
        import copy
        config = copy.deepcopy(self._load_profile())
        raw_tag: str = self._servers_config.servers[server_name].tag
        norm_sub = self._normalize_tag(raw_tag)

        # Find the real outbound tag by normalized substring match
        target: str | None = None
        for ob in config.get("outbounds", []):
            if norm_sub in self._normalize_tag(ob.get("tag", "")):
                target = ob["tag"]
                break
        if target is None:
            raise KeyError("Server %r not found in profile" % server_name)

        # Replace urltest_out with chosen server tag in all route rules
        for rule in config.get("route", {}).get("rules", []):
            if rule.get("outbound") == "urltest_out":
                rule["outbound"] = target
        if config.get("route", {}).get("final") == "urltest_out":
            config["route"]["final"] = target

        sanitized = self.sanitize_config(config)
        return json.dumps(sanitized, indent=2)

    def sanitize_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Remove or rewrite sing-box fields unsupported by the current runtime."""
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

        # Normalize all outbound tags (strip emoji suffixes from Akonit)
        for outbound in raw.get("outbounds", []):
            tag = outbound.get("tag", "")
            normalized = self._normalize_tag(tag)
            if normalized != tag:
                outbound["tag"] = normalized
                logger.info("Sanitized: normalized tag %r -> %r", tag, normalized)

        # Normalize route.final to match normalized outbound tags
        if "route" in raw and raw["route"].get("final"):
            raw["route"]["final"] = self._normalize_tag(raw["route"]["final"])

        # Normalize outbound references in route rules
        for rule in raw.get("route", {}).get("rules", []):
            ob = rule.get("outbound", "")
            if ob and ob != "urltest_out":
                rule["outbound"] = self._normalize_tag(ob)

        # Normalize outbound tags inside urltest/selector outbounds lists
        for outbound in raw.get("outbounds", []):
            if outbound.get("type") in ("urltest", "selector"):
                outbound["outbounds"] = [
                    self._normalize_tag(t) for t in outbound.get("outbounds", [])
                ]

        # Remove unsupported 'default' from urltest/selector outbounds
        for outbound in raw.get("outbounds", []):
            out_type: str | None = outbound.get("type")
            if out_type in ("urltest", "selector", "url-test"):
                outbound.pop("default", None)

        # Convert remote rule_sets to local when .srs cache exists.
        # This prevents sing-box from trying to download geoip/geosite at startup
        # when the VPN isn't up yet (chicken-and-egg problem).
        import os
        for rset in raw.get("route", {}).get("rule_set", []):
            if rset.get("type") == "remote":
                tag: str = rset.get("tag", "")
                cache_path: str = "/var/lib/sing-box/%s.srs" % tag.replace(":", "-")
                if os.path.exists(cache_path):
                    rset["type"] = "local"
                    rset["path"] = cache_path
                    rset.pop("url", None)
                    rset.pop("download_detour", None)
                    rset.pop("update_interval", None)
                    logger.info("Sanitized: converted remote rule_set %s to local (%s)", tag, cache_path)
                # else: leave as remote — container may have direct internet or will fail gracefully

        return raw
