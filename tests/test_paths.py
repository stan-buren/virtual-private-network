"""Tests for path resolution SSOT."""

from __future__ import annotations

from pathlib import Path

from vpn.config.paths import PROJECT_ROOT, load_paths_config


class TestProjectRoot:
    """Tests for PROJECT_ROOT resolution."""

    def test_project_root_is_absolute(self) -> None:
        """PROJECT_ROOT must be an absolute path."""
        assert PROJECT_ROOT.is_absolute()

    def test_project_root_contains_paths_config(self) -> None:
        """PROJECT_ROOT must contain config/paths.yaml."""
        assert (PROJECT_ROOT / "config" / "paths.yaml").exists()


class TestLoadPathsConfig:
    """Tests for load_paths_config() function."""

    def test_returns_dict_with_expected_keys(self) -> None:
        """load_paths_config must return a dict with known keys from paths.yaml."""
        paths = load_paths_config(PROJECT_ROOT)
        assert isinstance(paths, dict)
        assert "ru_subnets" in paths
        assert "profile_keys" in paths

    def test_dynamic_path_attributes_are_resolved(self) -> None:
        """Dynamically injected path constants must resolve to Path objects."""
        from vpn.config.paths import ru_subnets

        assert isinstance(ru_subnets, Path)
