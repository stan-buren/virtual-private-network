"""Speedtest orchestration: run Ookla speedtest per server, store and render.

The CLI drives the runs; results live under <cache_dir>/speedtest and are wiped
by the daemon on startup so no stale history accumulates between sessions.
"""

from vpn.core.speedtest.render import render_table
from vpn.core.speedtest.runner import SpeedtestError, SpeedtestRunner
from vpn.core.speedtest.store import SpeedtestStore

__all__ = ["SpeedtestStore", "SpeedtestRunner", "SpeedtestError", "render_table"]

