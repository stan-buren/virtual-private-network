"""JSON-RPC client for communicating with the VPN daemon over Unix socket."""

from __future__ import annotations

import json
import socket

SOCK = "/var/run/vpn.sock"


def call(method: str, params: dict | None = None) -> dict | list | str:
    """Send a JSON-RPC request to the daemon and return the result.

    Args:
        method: RPC method name (e.g. 'server.list').
        params: Optional keyword arguments for the method.

    Returns:
        The result field from the JSON-RPC response.

    Raises:
        RuntimeError: If the daemon returns an error.
        ConnectionRefusedError: If the daemon is not running.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(SOCK)
    sock.sendall(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
                "id": 1,
            }
        ).encode()
    )
    sock.shutdown(socket.SHUT_WR)
    data = sock.recv(65536)
    sock.close()
    resp = json.loads(data)
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp["result"]
