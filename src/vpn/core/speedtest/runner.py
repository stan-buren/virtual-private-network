"""Run the Ookla Speedtest CLI and normalise its JSON output."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")


class SpeedtestError(RuntimeError):
    """Raised when a speedtest run fails or returns unparseable output."""


class SpeedtestRunner:
    """Wraps the speedtest binary, returning a normalised result dict.

    The Ookla CLI is flaky: it can exit non-zero with "Cannot read from socket"
    or "Cannot retrieve configuration document" even though the tunnel itself is
    fine, and it may still print a usable result document.  We therefore parse
    stdout first (salvaging a partial result when present) and only then treat a
    non-zero exit as a failure, retrying a bounded number of times.
    """

    def __init__(
        self,
        shell: ShellPort,
        binary: str = "speedtest",
        timeout: int = 150,
        attempts: int = 2,
        retry_delay: int = 3,
    ) -> None:
        """Store the shell port, binary name, per-run timeout, and retry policy."""
        self._shell = shell
        self._binary = binary
        self._timeout = timeout
        self._attempts = max(1, attempts)
        self._retry_delay = retry_delay

    def command(self) -> str:
        """Return the shell command used to run the test."""
        return f"{self._binary} -f json --accept-license --accept-gdpr --progress=no"

    def run(self) -> dict[str, Any]:
        """Run a speedtest and return the normalised result, retrying failures.

        Raises:
            SpeedtestError: On a timeout, bad JSON, or repeated non-zero exit.
        """
        last_error: SpeedtestError | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                return self._run_once()
            except SpeedtestError as exc:
                last_error = exc
                if attempt < self._attempts:
                    logger.info(
                        "speedtest attempt %d/%d failed: %s",
                        attempt,
                        self._attempts,
                        exc,
                    )
                    time.sleep(self._retry_delay)
        assert last_error is not None
        raise last_error

    def _run_once(self) -> dict[str, Any]:
        """Execute one speedtest attempt, salvaging partial JSON when possible."""
        result = self._shell.run(self.command(), capture=True, timeout=self._timeout)
        if result is None:
            raise SpeedtestError("speedtest timed out")

        raw = self._parse_stdout(result.stdout)
        if raw is not None:
            return self.normalize(raw)

        if result.returncode != 0:
            raise SpeedtestError(self._failure_reason(result))
        raise SpeedtestError("invalid speedtest JSON")

    @staticmethod
    def _parse_stdout(stdout: str | None) -> dict[str, Any] | None:
        """Return the parsed result document from stdout, if it is usable."""
        if not stdout:
            return None
        try:
            raw = json.loads(stdout)
        except ValueError:
            return None
        if not isinstance(raw, dict):
            return None
        if not (raw.get("download") or raw.get("upload")):
            return None
        return raw

    @staticmethod
    def _failure_reason(result: Any) -> str:
        """Build a short, human-readable failure reason from the CLI output."""
        reason = ""
        for line in (getattr(result, "stderr", "") or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("message"):
                reason = str(parsed["message"])
            else:
                reason = line
        reason = reason.strip()
        if reason:
            return f"speedtest failed: {reason[:180]}"
        return f"speedtest exited with code {getattr(result, 'returncode', '?')}"

    @staticmethod
    def normalize(raw: dict[str, Any]) -> dict[str, Any]:
        """Map the Ookla JSON payload to our flat result schema."""
        ping = raw.get("ping") or {}
        download = raw.get("download") or {}
        upload = raw.get("upload") or {}
        server = raw.get("server") or {}
        dl_bw = download.get("bandwidth") or 0
        ul_bw = upload.get("bandwidth") or 0
        location = ", ".join(
            part for part in [server.get("location"), server.get("country")] if part
        )
        return {
            "download_mbps": round(dl_bw * 8 / 1_000_000, 2),
            "upload_mbps": round(ul_bw * 8 / 1_000_000, 2),
            "ping_ms": ping.get("latency"),
            "jitter_ms": ping.get("jitter"),
            "packet_loss_pct": raw.get("packetLoss"),
            "speedtest_server": server.get("name"),
            "speedtest_location": location or None,
            "external_ip": (raw.get("interface") or {}).get("externalIp"),
            "result_url": (raw.get("result") or {}).get("url"),
        }

