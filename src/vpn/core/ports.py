"""Port interfaces — contracts between core business logic and adapter implementations.

Every core module depends on these Protocol classes, never on concrete adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from subprocess import CompletedProcess
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass(frozen=True)
class ServerInfo:
    """Information about a single VPN server endpoint.

    Attributes:
        name: Short CLI name (e.g. 'barguzin').
        tag: Provider-specific outbound tag from profile JSON.
        country: ISO 3166-1 alpha-2 country code.
        host: Server IP address or hostname.
        port: Server port number.
    """

    name: str
    tag: str
    country: str
    host: str
    port: int


@dataclass
class PopenHandle:
    """Wraps a subprocess handle for clean lifecycle management.

    Attributes:
        pid: The process ID.
        poll: Callable returning exit code or None if still running.
        terminate: Callable to send SIGTERM.
        kill: Callable to send SIGKILL.
        wait: Callable to block until process exit.
    """

    pid: int
    poll: Callable[[], int | None]
    terminate: Callable[[], None]
    kill: Callable[[], None]
    wait: Callable[[float | None], int]


@runtime_checkable
class ShellPort(Protocol):
    """Executes shell commands with timeout and output capture."""

    def run(
        self, cmd: str, *, capture: bool = False, timeout: int = 20
    ) -> CompletedProcess | None: ...


@runtime_checkable
class FilesystemPort(Protocol):
    """Reads, writes, and queries the filesystem."""

    def read_text(self, path: str) -> str: ...
    def read_json(self, path: str) -> dict[str, Any]: ...
    def write_text(self, path: str, content: str) -> None: ...
    def write_json(self, path: str, data: dict[str, Any]) -> None: ...
    def exists(self, path: str) -> bool: ...
    def copy(self, src: str, dst: str) -> None: ...
    def makedirs(self, path: str) -> None: ...


@runtime_checkable
class HttpPort(Protocol):
    """Sends HTTP requests."""

    def post(self, url: str, data: bytes, timeout: int) -> None: ...


@runtime_checkable
class SubprocessPort(Protocol):
    """Launches and manages background subprocesses."""

    def popen(self, args: list[str]) -> PopenHandle: ...


@runtime_checkable
class VpnProviderPort(Protocol):
    """Contract every VPN provider adapter must fulfill.

    The core knows nothing about Akonit, Vanya, or any specific provider.
    It only knows this interface.
    """

    def list_servers(self) -> list[ServerInfo]:
        """Return all available servers with name, country, IP, port."""
        ...

    def get_server(self, name: str) -> ServerInfo:
        """Return a specific server by short name (e.g. 'barguzin').

        Raises:
            KeyError: If the server name is not found.
        """
        ...

    def build_singbox_config(self, server_name: str) -> str:
        """Build a complete sing-box config.json for the given server.

        Returns the JSON string ready to write to /etc/sing-box/config.json.
        """
        ...

    def sanitize_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Clean provider-specific incompatible fields from a sing-box config dict.

        Returns the sanitized dict.
        """
        ...
