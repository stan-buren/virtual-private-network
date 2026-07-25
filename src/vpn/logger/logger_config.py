"""VPN Daemon Logging Configuration Module.

Provides centralized, package-scoped logging configuration ensuring structured
and machine-readable outputs without polluting the global root logger namespace.
"""

from __future__ import annotations

import logging
import sys

from vpn.logger.core.json_formatter import JsonFormatter


def setup_logging(level: int = logging.INFO, use_json: bool = False) -> None:
    """Configures the package-level logger named 'vpn'.

    Attaches a standard stdout stream handler and sets either a structured
    human-readable text formatter or a machine-readable JSON formatter.
    Disables log propagation upward to avoid duplication and third-party
    library clutter.

    Args:
        level: The logging severity threshold (e.g., logging.INFO).
        use_json: If True, uses the JsonFormatter for syslog ingestion;
            otherwise uses a human-readable text format.
    """
    logger = logging.getLogger("vpn")
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)

        if use_json:
            formatter = JsonFormatter()
        else:
            formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d | %(message)s"
            )

        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
