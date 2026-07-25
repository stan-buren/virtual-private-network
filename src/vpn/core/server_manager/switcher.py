"""Server switcher — switches the active VPN server via the provider adapter."""

from __future__ import annotations

import logging

from vpn.core.ports import FilesystemPort, ShellPort, VpnProviderPort

logger = logging.getLogger("vpn")


class ServerSwitcher:
    """Switches the active VPN server by regenerating the sing-box config.

    Delegates to the provider adapter for provider-specific config generation.
    """

    def __init__(
        self,
        provider: VpnProviderPort,
        fs: FilesystemPort,
        shell: ShellPort,
        config_dest: str,
    ):
        self._provider = provider
        self._fs = fs
        self._shell = shell
        self._config_dest = config_dest

    def switch(self, server_name: str, restart_service: bool = True) -> str:
        """Switch to the named server.

        Args:
            server_name: Short CLI name (e.g. 'barguzin').
            restart_service: If True, restart sing-box after writing config.

        Returns:
            The tag of the newly activated server.

        Raises:
            KeyError: If server_name is not found.
        """
        old_server = self._current_server_tag()
        config_json = self._provider.build_singbox_config(server_name)
        logger.info("Writing new sing-box config for server: %s", server_name)
        self._fs.write_text(self._config_dest, config_json)

        if restart_service:
            logger.info("Restarting sing-box service")
            self._shell.run("pkill sing-box 2>/dev/null || true")
            import time
            time.sleep(1)

        new_server = self._provider.get_server(server_name)
        logger.info(
            "Server switched: %s -> %s (%s)",
            old_server or "none",
            new_server.tag,
            new_server.country,
        )
        return new_server.tag

    def list_servers(self) -> list:
        """Return all available servers from the provider."""
        return self._provider.list_servers()

    def _current_server_tag(self) -> str | None:
        """Read the currently active server tag from the config file."""
        if not self._fs.exists(self._config_dest):
            return None
        try:
            data = self._fs.read_json(self._config_dest)
            outbounds = data.get("outbounds", [])
            for ob in outbounds:
                if ob.get("tag") == "vless-out":
                    return ob.get("server", "unknown")
        except Exception:
            logger.exception("Failed to read current server from config")
        return None
