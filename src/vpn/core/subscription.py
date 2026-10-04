"""Fetch, merge and apply the provider subscription (sing-box profile JSON).

The provider subscription only ships log/dns/outbounds/route. Our container
needs its own inbounds (a local SOCKS/mixed listener that tun2socks dials), so
the subscription outbounds are merged onto a local baseline. The auto-select
group is also normalised to the tag the switcher expects.
"""

from __future__ import annotations

import glob
import json
import logging
import os
from typing import Any

from vpn.core.ports import FilesystemPort

logger = logging.getLogger("vpn")

SELECTOR_TYPES = ("urltest", "selector")
SWITCH_TAG = "urltest_out"


class SubscriptionError(RuntimeError):
    """Raised when the subscription payload is missing or invalid."""


def validate_profile(text: str) -> dict[str, Any]:
    """Parse and sanity-check a sing-box subscription payload.

    Args:
        text: Raw subscription body.

    Returns:
        The parsed profile dict.

    Raises:
        SubscriptionError: If the payload is not valid sing-box JSON with at
            least one vless outbound.
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SubscriptionError(f"subscription is not valid JSON: {exc}") from exc
    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list) or not outbounds:
        raise SubscriptionError("subscription has no outbounds")
    vless = [o for o in outbounds if isinstance(o, dict) and o.get("type") == "vless"]
    if not vless:
        raise SubscriptionError("subscription has no vless outbounds")
    return data


def _replace_refs(node: Any, old: str, new: str) -> None:
    """Recursively replace any string reference equal to *old* with *new*.

    Covers route.final, rule outbound, dns detour, and any other place the
    outbound tag is referenced by name.
    """
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if isinstance(value, str) and value == old:
                node[key] = new
            else:
                _replace_refs(value, old, new)
    elif isinstance(node, list):
        for item in node:
            _replace_refs(item, old, new)


def normalize_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Rename the auto-select group to the tag the switcher expects.

    The provider names its urltest group dynamically (e.g. an auto node); the
    daemon replaces the tag SWITCH_TAG to pin a concrete server, so the group
    and every reference to it must use that tag.
    """
    for outbound in data.get("outbounds", []):
        if not isinstance(outbound, dict):
            continue
        if outbound.get("type") in SELECTOR_TYPES:
            tag = outbound.get("tag")
            if tag and tag != SWITCH_TAG:
                outbound["tag"] = SWITCH_TAG
                _replace_refs(data, tag, SWITCH_TAG)
    return data


def merge_profile(subscription: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Merge the subscription onto the local baseline (inbounds, etc.)."""
    merged = {**baseline, **subscription}
    return normalize_profile(merged)


class SubscriptionUpdater:
    """Writes a merged subscription profile to the local profile path."""

    def __init__(
        self,
        fs: FilesystemPort,
        target_path: str,
        legacy_patterns: list[str] | None = None,
        baseline: dict[str, Any] | None = None,
    ) -> None:
        """Store the filesystem port, target path, legacy globs and baseline."""
        self._fs = fs
        self._target = target_path
        self._legacy = legacy_patterns or []
        self._baseline = baseline or {}

    def apply(self, text: str) -> dict[str, Any]:
        """Validate, merge, write the profile, and prune legacy profile files.

        Returns:
            Summary dict with target path, server count, and removed files.
        """
        data = merge_profile(validate_profile(text), self._baseline)
        outbounds = [o for o in data.get("outbounds", []) if o.get("type") == "vless"]
        target = os.path.abspath(self._target)
        self._fs.makedirs(os.path.dirname(target))
        self._fs.write_text(target, json.dumps(data, indent=2, ensure_ascii=False))
        removed = self._cleanup(target)
        return {
            "target": target,
            "server_count": len(outbounds),
            "has_inbounds": bool(data.get("inbounds")),
            "removed": removed,
        }

    def _cleanup(self, target: str) -> list[str]:
        """Delete legacy profile files matching the configured patterns."""
        removed: list[str] = []
        for pattern in self._legacy:
            for path in glob.glob(pattern):
                if os.path.abspath(path) == target:
                    continue
                try:
                    os.remove(path)
                    removed.append(path)
                except OSError:
                    logger.warning("could not remove legacy profile: %s", path)
        return removed

