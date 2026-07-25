"""Path resolution module — Single Source of Truth for all filesystem paths.

Reads config/paths.yaml and exposes every path as a module-level constant
resolved relative to PROJECT_ROOT. All other modules import paths from here.
"""

from __future__ import annotations

import os
import typing
from pathlib import Path

import yaml


def _find_project_root() -> Path:
    """Locates the project root by searching for config/paths.yaml upward.

    Returns:
        Path: The absolute project root directory.

    Raises:
        FileNotFoundError: If config/paths.yaml cannot be found.
    """
    # Check env var first (set by Dockerfile / container runtime)
    env_root = os.environ.get("PROJECT_ROOT", "")
    if env_root:
        candidate = Path(env_root) / "config" / "paths.yaml"
        if candidate.exists():
            return Path(env_root)
    # Fallback: walk up from this file's location
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "config" / "paths.yaml"
        if candidate.exists():
            return current
        if current.parent == current:
            break
    raise FileNotFoundError(
        "Cannot locate project root: config/paths.yaml not found in any parent directory."
    )


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
