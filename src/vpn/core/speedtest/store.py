"""File-based storage for speedtest results and run status.

Lives under <cache_dir>/speedtest. Shared between CLI processes through the
container filesystem. The daemon wipes the directory on startup so old runs do
not survive a restart.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

SUBDIR = "speedtest"
STATUS_FILE = "status.json"
LOCK_FILE = ".lock"
STALE_TTL = 900  # seconds before a lock with no active run is reclaimed


class SpeedtestStore:
    """Reads/writes speedtest results and the shared run status."""

    def __init__(self, cache_dir: str | os.PathLike[str]) -> None:
        """Initialise the store rooted at cache_dir."""
        self.root = Path(cache_dir) / SUBDIR

    # -- lifecycle ---------------------------------------------------------
    def ensure(self) -> None:
        """Create the results directory if it does not exist."""
        self.root.mkdir(parents=True, exist_ok=True)

    def clear(self) -> None:
        """Remove every stored result and the status file."""
        shutil.rmtree(self.root, ignore_errors=True)

    # -- results -----------------------------------------------------------
    def _result_path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def write_result(self, name: str, payload: dict[str, Any]) -> None:
        """Persist a single server result as JSON."""
        self.ensure()
        self._result_path(name).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def read_result(self, name: str) -> dict[str, Any] | None:
        """Return a stored result, or None if it was never written."""
        path = self._result_path(name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def all_results(self) -> dict[str, dict[str, Any]]:
        """Return every stored result keyed by server name."""
        out: dict[str, dict[str, Any]] = {}
        if not self.root.exists():
            return out
        for path in sorted(self.root.glob("*.json")):
            if path.name == STATUS_FILE:
                continue
            try:
                out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
        return out

    # -- status ------------------------------------------------------------
    def write_status(self, status: dict[str, Any]) -> None:
        """Write the shared run status document."""
        self.ensure()
        (self.root / STATUS_FILE).write_text(
            json.dumps(status, indent=2), encoding="utf-8"
        )
        lock = self.root / LOCK_FILE
        if lock.exists():
            try:
                os.utime(lock, None)
            except OSError:
                pass

    def read_status(self) -> dict[str, Any]:
        """Read the shared run status document (empty dict if absent)."""
        path = self.root / STATUS_FILE
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def is_running(self) -> bool:
        """True while a live speedtest run is in progress.

        Requires the run lock to be present and fresh, so a stale status left
        behind by an interrupted run does not block the view command.
        """
        lock = self.root / LOCK_FILE
        if not lock.exists():
            return False
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return False
        if age > STALE_TTL:
            return False
        return bool(self.read_status().get("running"))

    # -- lock --------------------------------------------------------------
    def acquire(self) -> bool:
        """Atomically claim the run lock.

        A stale lock (present but no run marked running) is reclaimed so a
        crashed run cannot wedge the command forever.

        Returns:
            True if the lock was acquired, False if a run is already active.
        """
        self.ensure()
        lock = self.root / LOCK_FILE
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                return False
            if age < STALE_TTL:
                return False
            try:
                lock.unlink()
            except OSError:
                return False
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return True
            except OSError:
                return False

    def release(self) -> None:
        """Release the run lock."""
        (self.root / LOCK_FILE).unlink(missing_ok=True)

