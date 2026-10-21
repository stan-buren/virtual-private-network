"""Structured operational events — one JSON object per line.

Every event answers the same five questions, so a failure can be diagnosed
from the log alone without re-reading the source:

    layer       which layer of the stack produced the observation
    verdict     ok | fail | warn | info
    latency_ms  how long the operation took (null when not measured)
    error_class stable machine-readable reason (null when the verdict is ok)
    action      what the daemon did about it, and its cost
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

_event_logger = logging.getLogger("vpn.event")


def emit(
    layer: str,
    verdict: str,
    action: str,
    *,
    cost: str = "none",
    latency_ms: float | None = None,
    error_class: str | None = None,
    **extra: object,
) -> None:
    """Write one structured event line.

    Args:
        layer: L0 (process/device), L1 (egress), L2 (routing), CFG (config),
            CLI (operator action) or SYS (daemon lifecycle).
        verdict: ok, fail, warn or info.
        action: what the daemon did, or "none" when it only observed.
        cost: none, cheap, restart, route-change or disruptive.
        latency_ms: measured duration in milliseconds.
        error_class: stable reason token, e.g. dial_timeout, no_socks, stale_tun.
        **extra: additional context (server, target, pid, routes, ...).
    """
    record: dict[str, object] = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "layer": layer,
        "verdict": verdict,
        "action": action,
        "cost": cost,
        "latency_ms": None if latency_ms is None else round(latency_ms, 1),
        "error_class": error_class,
    }
    for key, value in extra.items():
        if value is not None:
            record[key] = value
    _event_logger.info(json.dumps(record, ensure_ascii=False, sort_keys=True))


def now() -> float:
    """Monotonic timestamp for measuring durations."""
    return time.monotonic()
