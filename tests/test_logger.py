"""Tests for logger module — exceptions, formatter, configuration."""

from __future__ import annotations

import json
import logging

from vpn.logger import (
    VpnConfigError,
    VpnConnectionError,
    VpnError,
    VpnHealthError,
    VpnTunnelError,
    setup_logging,
)
from vpn.logger.core.json_formatter import JsonFormatter


class TestExceptions:
    """Verify the VpnError exception hierarchy."""

    def test_all_inherit_from_vpn_error(self) -> None:
        """All domain exceptions must subclass VpnError."""
        assert issubclass(VpnConfigError, VpnError)
        assert issubclass(VpnConnectionError, VpnError)
        assert issubclass(VpnTunnelError, VpnError)
        assert issubclass(VpnHealthError, VpnError)

    def test_vpn_error_is_exception(self) -> None:
        """VpnError itself must be a standard Exception."""
        assert issubclass(VpnError, Exception)


class TestSetupLogging:
    """Verify setup_logging() configures the 'vpn' logger correctly."""

    def test_creates_scoped_logger(self) -> None:
        """setup_logging creates a scoped 'vpn' logger with handlers."""
        setup_logging(level=logging.DEBUG, use_json=False)
        logger = logging.getLogger("vpn")
        assert logger.level == logging.DEBUG
        assert logger.propagate is False
        assert len(logger.handlers) >= 1

    def test_idempotent_no_duplicate_handlers(self) -> None:
        """Repeated calls to setup_logging do not add extra handlers."""
        setup_logging()
        setup_logging()
        logger = logging.getLogger("vpn")
        handler_count = len(logger.handlers)
        setup_logging()
        assert len(logger.handlers) == handler_count


class TestJsonFormatter:
    """Verify JsonFormatter produces valid structured JSON output."""

    def test_formats_record_as_json(self) -> None:
        """A LogRecord is formatted as a single-line JSON document."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            "vpn", logging.INFO, "test.py", 42, "test message", (), None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "test message"
        assert "timestamp" in parsed
