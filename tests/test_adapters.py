"""Tests for adapter implementations — each satisfies its Protocol."""

from __future__ import annotations

from vpn.adapters.http.urllib_http import UrllibHttpAdapter
from vpn.adapters.system.filesystem import FilesystemAdapter
from vpn.adapters.system.shell import ShellAdapter
from vpn.adapters.system.subprocess import SubprocessAdapter
from vpn.core.ports import FilesystemPort, HttpPort, ShellPort, SubprocessPort


class TestShellAdapter:
    def test_implements_shell_port(self) -> None:
        adapter = ShellAdapter()
        assert isinstance(adapter, ShellPort)

    def test_run_returns_completed_process(self) -> None:
        adapter = ShellAdapter()
        result = adapter.run("echo hello", capture=True)
        assert result is not None
        assert result.returncode == 0


class TestFilesystemAdapter:
    def test_implements_filesystem_port(self) -> None:
        adapter = FilesystemAdapter()
        assert isinstance(adapter, FilesystemPort)

    def test_exists_returns_bool(self) -> None:
        adapter = FilesystemAdapter()
        assert adapter.exists("/") is True
        assert adapter.exists("/nonexistent_path_xyz") is False


class TestSubprocessAdapter:
    def test_implements_subprocess_port(self) -> None:
        adapter = SubprocessAdapter()
        assert isinstance(adapter, SubprocessPort)


class TestUrllibHttpAdapter:
    def test_implements_http_port(self) -> None:
        adapter = UrllibHttpAdapter()
        assert isinstance(adapter, HttpPort)
