"""Tests for Click CLI commands."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from click.testing import CliRunner

from vpn.cli.main import cli


class TestCli:
    """Tests for the top-level CLI group and its subcommands."""

    def test_help_shows_commands(self) -> None:
        """--help lists server, status, and bypass command groups."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "server" in result.output
        assert "status" in result.output
        assert "bypass" in result.output

    def test_server_list(self) -> None:
        """server list exits successfully with mocked IPC."""
        with patch("vpn.cli.main.ipc_call", return_value=[]):
            runner = CliRunner()
            result = runner.invoke(cli, ["server", "list"])
            assert result.exit_code == 0

    def test_server_change_requires_name(self) -> None:
        """server change fails when --name is omitted."""
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "change"])
        assert result.exit_code != 0

    def test_status(self) -> None:
        """status exits successfully with mocked IPC."""
        with patch("vpn.cli.main.ipc_call", return_value={"gateway": "10.0.0.1"}):
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0

    def test_restart(self) -> None:
        """restart exits successfully with mocked IPC."""
        with patch("vpn.cli.main.ipc_call", return_value={"status": "ok"}):
            runner = CliRunner()
            result = runner.invoke(cli, ["restart"])
            assert result.exit_code == 0

    @pytest.mark.skip(reason="emergency-reset command not yet implemented")
    def test_emergency_reset(self) -> None:
        """emergency-reset exits successfully."""
        with patch("vpn.cli.main.ipc_call", return_value={"status": "ok"}):
            runner = CliRunner()
            result = runner.invoke(cli, ["emergency-reset"])
            assert result.exit_code == 0
    def test_bypass_list(self) -> None:
        """bypass list exits successfully with mocked IPC."""
        with patch("vpn.cli.main.ipc_call", return_value=[]):
            runner = CliRunner()
            result = runner.invoke(cli, ["bypass", "list"])
            assert result.exit_code == 0

    def test_server_current(self) -> None:
        """server current exits successfully with mocked IPC."""
        with patch("vpn.cli.main.ipc_call", return_value={"barguzin": "some tag"}):
            runner = CliRunner()
            result = runner.invoke(cli, ["server", "current"])
            assert result.exit_code == 0

    def test_server_change_succeeds_with_name(self) -> None:
        """server change --name <value> exits successfully with mocked IPC."""
        with patch("vpn.cli.main.ipc_call", return_value="barguzin"):
            runner = CliRunner()
            result = runner.invoke(cli, ["server", "change", "barguzin"])
            assert result.exit_code == 0
