"""tun2socks process lifecycle management."""

from __future__ import annotations

import logging

from vpn.core.ports import PopenHandle, SubprocessPort

logger = logging.getLogger("vpn")


class Tun2SocksManager:
    """Manages the tun2socks process that bridges tun0 to the SOCKS5 proxy."""

    def __init__(self, subprocess: SubprocessPort):
        self._subprocess = subprocess
        self._handle: PopenHandle | None = None

    @property
    def is_alive(self) -> bool:
        """Check if the tun2socks process is currently running."""
        if self._handle is None:
            return False
        return self._handle.poll() is None

    def start(self, proxy_url: str) -> PopenHandle:
        """Launch tun2socks pointing to the configured proxy.

        Args:
            proxy_url: SOCKS5 proxy URL (e.g. 'socks5://127.0.0.1:3066').

        Returns:
            PopenHandle for the launched process.
        """
        if self._handle and self.is_alive:
            logger.info("Stopping old tun2socks process (PID %d)", self._handle.pid)
            self._handle.terminate()
            try:
                self._handle.wait(5)
            except Exception:
                self._handle.kill()
                self._handle.wait(None)

        logger.info("Starting tun2socks with proxy: %s", proxy_url)
        self._handle = self._subprocess.popen(
            ["tun2socks", "-device", "tun0", "-proxy", proxy_url]
        )
        logger.info("tun2socks started (PID %d)", self._handle.pid)
        return self._handle

    def stop(self) -> None:
        """Stop the tun2socks process gracefully."""
        if self._handle and self.is_alive:
            logger.info("Stopping tun2socks (PID %d)", self._handle.pid)
            self._handle.terminate()
            try:
                self._handle.wait(5)
            except Exception:
                self._handle.kill()
                self._handle.wait(None)
            self._handle = None
