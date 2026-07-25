"""Optional SSH tunnel to MacBook SOCKS5 proxy."""

from __future__ import annotations

import logging

from vpn.core.ports import PopenHandle, SubprocessPort

logger = logging.getLogger("vpn")


class SshTunnel:
    """Opens an SSH SOCKS5 tunnel to a remote host (e.g. MacBook).

    This is an optional feature for scenarios where the local sing-box
    cannot reach the VPN server directly.
    """

    def __init__(self, subprocess: SubprocessPort):
        self._subprocess = subprocess
        self._handle: PopenHandle | None = None

    def open(self, user: str, host: str, port: int) -> PopenHandle:
        """Open an SSH dynamic SOCKS5 tunnel.

        Args:
            user: SSH username.
            host: Remote host IP.
            port: Local SOCKS5 port to bind.

        Returns:
            PopenHandle for the ssh process.
        """
        logger.info("Opening SSH tunnel to %s@%s:-D%d", user, host, port)
        self._handle = self._subprocess.popen(
            ["ssh", "-D", str(port), "-N", "%s@%s" % (user, host)]
        )
        logger.info("SSH tunnel opened (PID %d)", self._handle.pid)
        return self._handle

    def close(self) -> None:
        """Close the SSH tunnel."""
        if self._handle:
            logger.info("Closing SSH tunnel (PID %d)", self._handle.pid)
            self._handle.terminate()
            try:
                self._handle.wait(5)
            except Exception:
                self._handle.kill()
                self._handle.wait(None)
            self._handle = None
