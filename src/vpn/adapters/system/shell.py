"""Shell adapter — executes system commands via subprocess.run."""

from __future__ import annotations

import logging
import subprocess

from vpn.core.ports import ShellPort

logger = logging.getLogger("vpn")


class ShellAdapter:
    """Implements ShellPort by wrapping subprocess.run with logging."""

    def run(
        self, cmd: str, *, capture: bool = False, timeout: int = 20
    ) -> subprocess.CompletedProcess | None:
        logger.debug("Executing: %s", cmd)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=capture, text=True, timeout=timeout
            )
            logger.debug("Exit code: %d", result.returncode)
            if capture and result.stderr and result.returncode != 0:
                logger.warning("stderr: %s", result.stderr[:200].strip())
            return result
        except subprocess.TimeoutExpired:
            logger.error("Command timed out (%ds): %s", timeout, cmd)
            return None
        except Exception:
            logger.exception("Command failed: %s", cmd)
            return None
