"""Health check configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class HealthConfig:
    """Immutable health monitoring configuration.

    Attributes:
        check_interval_min: Minimum seconds between connectivity checks.
        check_interval_max: Maximum seconds between connectivity checks.
        fail_threshold: Consecutive failures before triggering recovery.
        curl_timeout: Timeout in seconds for curl health check requests.
        targets: HTTPS URLs to probe for connectivity verification.
        user_agents: User-Agent strings rotated randomly for stealth.
    """

    check_interval_min: int
    check_interval_max: int
    fail_threshold: int
    curl_timeout: int
    targets: list[str]
    user_agents: list[str]

    @classmethod
    def _from_yaml(cls) -> HealthConfig:
        """Loads and parses the health configuration from health.yaml."""
        from vpn.config.paths import CONFIG_DIR

        with (CONFIG_DIR / "health.yaml").open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        h = data["health"]
        return cls(
            check_interval_min=h["check_interval_min"],
            check_interval_max=h["check_interval_max"],
            fail_threshold=h["fail_threshold"],
            curl_timeout=h["curl_timeout"],
            targets=h["targets"],
            user_agents=h["user_agents"],
        )
