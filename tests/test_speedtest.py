"""Tests for the speedtest store, runner, renderer, and CLI commands."""

from __future__ import annotations

import json
import os

import pytest
from click.testing import CliRunner

from vpn.cli.main import cli
from vpn.core.speedtest import (
    SpeedtestError,
    SpeedtestRunner,
    SpeedtestStore,
    render_table,
)

SAMPLE = {
    "type": "result",
    "ping": {"jitter": 1.5, "latency": 12.0, "low": 11.0, "high": 13.0},
    "download": {"bandwidth": 12500000, "bytes": 1, "elapsed": 1, "latency": {}},
    "upload": {"bandwidth": 1250000, "bytes": 1, "elapsed": 1, "latency": {}},
    "packetLoss": 0,
    "server": {"id": 1, "name": "Local", "location": "Amsterdam", "country": "NL"},
    "interface": {"externalIp": "1.2.3.4"},
    "result": {"url": "https://example/result"},
}


class FakeShell:
    """Shell port stub returning a canned CompletedProcess-like object."""

    def __init__(
        self, stdout: str = "", returncode: int = 0, result=None, stderr: str = ""
    ):
        self._stdout = stdout
        self._rc = returncode
        self._stderr = stderr
        self._result = result if result is not None else object()
        self._result = (
            None
            if result is None and getattr(self, "_force_none", False)
            else self._result
        )

    def run(self, cmd, *, capture=False, timeout=20):  # noqa: D401
        if self._result is None:
            return None
        return type(
            "R",
            (),
            {"returncode": self._rc, "stdout": self._stdout, "stderr": self._stderr},
        )


class SequencedShell:
    """Shell port stub returning a queued outcome per call."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def run(self, cmd, *, capture=False, timeout=20):  # noqa: D401
        self.calls += 1
        idx = min(self.calls - 1, len(self._outcomes) - 1)
        rc, stdout, stderr = self._outcomes[idx]
        return type("R", (), {"returncode": rc, "stdout": stdout, "stderr": stderr})


class TestStore:
    def test_write_read_all_clear(self, tmp_path):
        store = SpeedtestStore(tmp_path)
        store.write_result("a", {"download_mbps": 1.0})
        store.write_result("b", {"download_mbps": 2.0})
        assert store.read_result("a")["download_mbps"] == 1.0
        assert set(store.all_results()) == {"a", "b"}
        store.write_status({"running": False})
        assert "status" not in store.all_results()
        store.clear()
        assert store.all_results() == {}
        assert not store.root.exists()

    def test_missing_result(self, tmp_path):
        assert SpeedtestStore(tmp_path).read_result("nope") is None

    def test_acquire_release(self, tmp_path):
        store = SpeedtestStore(tmp_path)
        assert store.acquire() is True
        assert store.acquire() is False
        store.release()
        assert store.acquire() is True
        store.release()

    def test_stale_lock_reclaimed(self, tmp_path):
        store = SpeedtestStore(tmp_path)
        store.ensure()
        store.write_status({"running": False})
        lock = store.root / ".lock"
        lock.write_text("")
        os.utime(lock, (0, 0))
        assert store.acquire() is True
        store.release()

    def test_is_running(self, tmp_path):
        store = SpeedtestStore(tmp_path)
        assert store.is_running() is False
        store.write_status({"running": True})
        assert store.is_running() is False  # no lock -> not running
        assert store.acquire() is True
        store.write_status({"running": True})
        assert store.is_running() is True
        store.release()
        assert store.is_running() is False

    def test_corrupt_files_ignored(self, tmp_path):
        store = SpeedtestStore(tmp_path)
        store.ensure()
        (store.root / "bad.json").write_text("{not json")
        (store.root / "status.json").write_text("123")
        assert store.all_results() == {}
        assert store.read_status() == {}
        assert store.read_result("bad") is None


class TestRunner:
    def test_normalize(self):
        out = SpeedtestRunner.normalize(SAMPLE)
        assert out["download_mbps"] == 100.0
        assert out["upload_mbps"] == 10.0
        assert out["ping_ms"] == 12.0
        assert out["jitter_ms"] == 1.5
        assert out["packet_loss_pct"] == 0
        assert out["external_ip"] == "1.2.3.4"
        assert "Amsterdam" in out["speedtest_location"]

    def test_normalize_empty(self):
        out = SpeedtestRunner.normalize({})
        assert out["download_mbps"] == 0

    def test_run_ok(self):
        shell = FakeShell(stdout=json.dumps(SAMPLE), returncode=0)
        assert SpeedtestRunner(shell).run()["download_mbps"] == 100.0

    def test_run_nonzero(self):
        with pytest.raises(SpeedtestError):
            SpeedtestRunner(FakeShell(stdout="", returncode=1), attempts=1).run()

    def test_run_timeout(self):
        with pytest.raises(SpeedtestError):
            SpeedtestRunner(FakeShell(result=None), attempts=1).run()

    def test_run_bad_json(self):
        with pytest.raises(SpeedtestError):
            SpeedtestRunner(FakeShell(stdout="nope", returncode=0), attempts=1).run()

    def test_run_salvages_json_on_nonzero(self):
        shell = FakeShell(stdout=json.dumps(SAMPLE), returncode=2)
        assert SpeedtestRunner(shell, attempts=1).run()["download_mbps"] == 100.0

    def test_run_retries_then_succeeds(self):
        shell = SequencedShell([(2, "", "boom"), (0, json.dumps(SAMPLE), "")])
        runner = SpeedtestRunner(shell, attempts=2, retry_delay=0)
        assert runner.run()["download_mbps"] == 100.0
        assert shell.calls == 2

    def test_failure_reason_from_stderr(self):
        stderr = (
            '{"type":"log","message":"Error: [0] Cannot read from socket: "'
            ',"level":"error"}'
        )
        shell = FakeShell(stdout="", returncode=2, stderr=stderr)
        with pytest.raises(SpeedtestError, match="Cannot read from socket"):
            SpeedtestRunner(shell, attempts=1).run()

    def test_command(self):
        assert "--accept-license" in SpeedtestRunner(FakeShell()).command()


class TestRender:
    def test_empty(self):
        assert "No speedtest results" in render_table({})

    def test_rows(self):
        out = render_table(
            {
                "a": {
                    "country": "nl",
                    "download_mbps": 1.0,
                    "upload_mbps": 2.0,
                    "ping_ms": 3.0,
                    "jitter_ms": 0.5,
                    "packet_loss_pct": 0,
                    "external_ip": "9.9.9.9",
                    "tested_at": "now",
                }
            }
        )
        assert "a" in out and "nl" in out and "1.0" in out

    def test_error_row(self):
        out = render_table({"a": {"error": "boom", "tested_at": "now"}})
        assert "ERR" in out


class FakeRunner:
    """Stub SpeedtestRunner returning a canned result."""

    def __init__(self, *args, **kwargs):
        pass

    def run(self):
        return {
            "download_mbps": 5.0,
            "upload_mbps": 1.0,
            "ping_ms": 10.0,
            "jitter_ms": 1.0,
            "packet_loss_pct": 0,
            "external_ip": "8.8.8.8",
        }


class FailRunner(FakeRunner):
    def run(self):
        raise SpeedtestError("boom")


class TestCli:
    def test_speedtest_requires_selection(self):
        result = CliRunner().invoke(cli, ["server", "speedtest"])
        assert result.exit_code != 0

    def test_speedtest_view_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("vpn.cli.main._cache_dir", lambda: str(tmp_path))
        result = CliRunner().invoke(cli, ["server", "speedtest", "view"])
        assert result.exit_code == 0
        assert "No speedtest results" in result.output

    def test_speedtest_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr("vpn.cli.main._cache_dir", lambda: str(tmp_path))
        monkeypatch.setattr("vpn.cli.main._switch_and_wait", lambda name: None)
        monkeypatch.setattr("vpn.cli.main.SpeedtestRunner", lambda shell: FakeRunner())

        def fake_ipc(method, params=None):
            if method == "server.list":
                return [{"name": "harmonik", "country": "nl"}]
            if method == "server.current":
                return {"server": None}
            return {}

        monkeypatch.setattr("vpn.cli.main.ipc_call", fake_ipc)
        result = CliRunner().invoke(cli, ["server", "speedtest", "--all"])
        assert result.exit_code == 0
        assert "harmonik" in result.output

    def test_speedtest_single_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr("vpn.cli.main._cache_dir", lambda: str(tmp_path))
        monkeypatch.setattr("vpn.cli.main._switch_and_wait", lambda name: None)
        monkeypatch.setattr("vpn.cli.main.SpeedtestRunner", lambda shell: FakeRunner())

        def fake_ipc(method, params=None):
            if method == "server.list":
                return [{"name": "harmonik", "country": "nl"}]
            if method == "server.current":
                return {"server": "harmonik"}
            return {}

        monkeypatch.setattr("vpn.cli.main.ipc_call", fake_ipc)
        result = CliRunner().invoke(cli, ["server", "speedtest", "--server", "harmonik"])
        assert result.exit_code == 0

    def test_speedtest_unknown_server(self, tmp_path, monkeypatch):
        monkeypatch.setattr("vpn.cli.main._cache_dir", lambda: str(tmp_path))
        monkeypatch.setattr("vpn.cli.main._switch_and_wait", lambda name: None)
        monkeypatch.setattr("vpn.cli.main.SpeedtestRunner", lambda shell: FakeRunner())

        def fake_ipc(method, params=None):
            if method == "server.list":
                return [{"name": "harmonik", "country": "nl"}]
            return {}

        monkeypatch.setattr("vpn.cli.main.ipc_call", fake_ipc)
        result = CliRunner().invoke(cli, ["server", "speedtest", "--server", "nope"])
        assert result.exit_code == 1

    def test_speedtest_error_recorded(self, tmp_path, monkeypatch):
        monkeypatch.setattr("vpn.cli.main._cache_dir", lambda: str(tmp_path))
        monkeypatch.setattr("vpn.cli.main._switch_and_wait", lambda name: None)
        monkeypatch.setattr("vpn.cli.main.SpeedtestRunner", lambda shell: FailRunner())

        def fake_ipc(method, params=None):
            if method == "server.list":
                return [{"name": "harmonik", "country": "nl"}]
            if method == "server.current":
                return {"server": None}
            return {}

        monkeypatch.setattr("vpn.cli.main.ipc_call", fake_ipc)
        result = CliRunner().invoke(cli, ["server", "speedtest", "--all"])
        assert result.exit_code == 0
        assert "ERROR" in result.output

    def test_speedtest_lock_busy(self, tmp_path, monkeypatch):
        store = SpeedtestStore(tmp_path)
        store.write_status({"running": True})
        store.ensure()
        (store.root / ".lock").write_text("")
        monkeypatch.setattr("vpn.cli.main._cache_dir", lambda: str(tmp_path))
        monkeypatch.setattr("vpn.cli.main.SpeedtestRunner", lambda shell: FakeRunner())
        monkeypatch.setattr("vpn.cli.main.ipc_call", lambda m, p=None: [])
        result = CliRunner().invoke(cli, ["server", "speedtest", "--all"])
        assert result.exit_code == 1

    def test_speedtest_view_waits(self, tmp_path, monkeypatch):
        store = SpeedtestStore(tmp_path)
        store.write_result("a", {"country": "nl", "download_mbps": 1.0})
        store.write_status({"running": False})
        monkeypatch.setattr("vpn.cli.main._cache_dir", lambda: str(tmp_path))
        result = CliRunner().invoke(cli, ["server", "speedtest", "view"])
        assert result.exit_code == 0
        assert "a" in result.output

