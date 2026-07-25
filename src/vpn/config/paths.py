"""Path resolution module — Single Source of Truth for all filesystem paths.

Reads config/paths.yaml and exposes every path as a module-level constant
resolved relative to PROJECT_ROOT. All other modules import paths from here.

Resolution strategy (three-tier fallback):
1. PROJECT_ROOT env var (Docker/container runtime)
2. .project_root marker file (walks up from this file's location)
3. Static parent lookup (3 levels up from src/vpn/config/)
"""

from __future__ import annotations

import os
import typing
from pathlib import Path

import yaml


def _find_project_root() -> Path:
    """Locate the project root directory deterministically.

    Three-tier fallback strategy:
    1. ``PROJECT_ROOT`` environment variable — takes precedence in
       Docker and production deployments.
    2. ``.project_root`` marker file — walks upward from this file's
       resolved location; first parent with ``.project_root`` wins.
    3. Static parent lookup — ``parents[3]`` from this file
       (``src/vpn/config/paths.py`` → ``src/`` → project root).

    Returns:
        Path: The absolute project root directory.

    Raises:
        FileNotFoundError: If no strategy resolves a valid root.
    """
    # Tier 1: Environment variable (Docker, Airflow, CI)
    if env_root := os.getenv("PROJECT_ROOT"):
        return Path(env_root)

    # Tier 2: .project_root marker file
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".project_root").exists():
            return parent

    # Tier 3: Static parent lookup
    # This file is at src/vpn/config/paths.py → 3 levels up = project root
    return current.parents[3]


PROJECT_ROOT: Path = _find_project_root()
PATHS_YAML: Path = PROJECT_ROOT / "config" / "paths.yaml"


def load_paths_config(project_root: Path) -> dict[str, str]:
    """Loads and parses the centralized paths configuration from paths.yaml.

    Args:
        project_root: The project root directory.

    Returns:
        dict[str, str]: Mapped relative path configurations keyed by path name.

    Raises:
        FileNotFoundError: If paths.yaml is missing.
        yaml.YAMLError: If paths.yaml contains invalid syntax.
    """
    paths_file = project_root / "config" / "paths.yaml"
    if not paths_file.exists():
        raise FileNotFoundError(
            "Paths configuration file not found at: %s", paths_file
        )
    with paths_file.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_paths_data: dict[str, str] = load_paths_config(PROJECT_ROOT)

# Resolve all declared paths relative to project root and inject into module namespace
for _key, _rel_val in _paths_data.items():
    globals()[_key] = PROJECT_ROOT / _rel_val

# Also expose the config directory directly
CONFIG_DIR: Path = PROJECT_ROOT / "config"

__all__ = ["PROJECT_ROOT", "CONFIG_DIR", "PATHS_YAML", "load_paths_config"]
__all__.extend(list(_paths_data.keys()))


def __getattr__(name: str) -> typing.Any:
    """Allow dynamic attribute access for static type checkers.

    Args:
        name: The attribute name to look up.

    Returns:
        The resolved Path object for the named path.

    Raises:
        AttributeError: If the name is not a known path key.
    """
    if name in __all__:
        return globals().get(name)
    raise AttributeError("module %r has no attribute %r", __name__, name)
