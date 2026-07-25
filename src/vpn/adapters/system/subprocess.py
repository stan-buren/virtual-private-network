"""Subprocess adapter — launches and manages background processes."""

from __future__ import annotations

import logging
import subprocess

from vpn.core.ports import PopenHandle, SubprocessPort

logger = logging.getLogger("vpn")


class SubprocessAdapter:
    """Implements SubprocessPort by wrapping subprocess.Popen."""

    def popen(self, args: list[str]) -> PopenHandle:
        logger.debug("Starting process: %s", args)
        proc = subprocess.Popen(
            args,
            stdout=None,
            stderr=None,
            start_new_session=True,
        )
        return PopenHandle(
            pid=proc.pid,
            poll=proc.poll,
            terminate=proc.terminate,
            kill=proc.kill,
            wait=proc.wait,
        )
