"""sing-box config deployer — copy, sanitize, write."""

from __future__ import annotations

import json
import logging

from vpn.core.ports import FilesystemPort, VpnProviderPort

logger = logging.getLogger("vpn")


class ConfigDeployer:
    """Deploys sing-box configuration: copy profile, sanitize, write to destination."""

    def __init__(
        self,
        provider: VpnProviderPort,
        fs: FilesystemPort,
        profile_path: str,
        config_dest: str,
    ):
        self._provider = provider
        self._fs = fs
        self._profile_path = profile_path
        self._config_dest = config_dest

    def deploy(self) -> bool:
        """Deploy the profile config to the sing-box destination.

        Copies the profile JSON if it exists, then sanitizes it in-place.

        Returns:
            True if deployment succeeded.
        """
        if not self._fs.exists(self._profile_path):
            logger.warning("Profile not found: %s", self._profile_path)
            if not self._fs.exists(self._config_dest):
                logger.error("No profile and no existing config — cannot deploy")
                return False
            logger.info("Using existing config at %s", self._config_dest)
        else:
            logger.info(
                "Copying profile %s -> %s", self._profile_path, self._config_dest
            )
            self._fs.copy(self._profile_path, self._config_dest)

        try:
            raw = json.loads(self._fs.read_text(self._config_dest))
            sanitized = self._provider.sanitize_config(raw)
            self._fs.write_text(
                self._config_dest, json.dumps(sanitized, indent=2)
            )
            logger.info("Config deployed and sanitized at %s", self._config_dest)
            return True
        except Exception:
            logger.exception("Config sanitization failed")
            return False
