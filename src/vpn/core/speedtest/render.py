"""Render a speedtest results table for the CLI."""

from __future__ import annotations

from typing import Any

HEADERS = ["Name", "CC", "Down", "Up", "Ping", "Jitter", "Loss", "Exit IP", "Tested"]
UNITS = ["", "", "Mbit/s", "Mbit/s", "ms", "ms", "%", "", ""]


def _fmt(value: Any, decimals: int = 1) -> str:
    """Format a numeric value for the table, using '-' for missing values."""
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:.{decimals}f}"
    return str(value)


def _row(name: str, result: dict[str, Any]) -> list[str]:
    if result.get("error"):
        return [name, result.get("country", "-"), "ERR", "-", "-", "-", "-", "-",
                str(result.get("tested_at", "-"))]
    return [
        name,
        result.get("country", "-"),
        _fmt(result.get("download_mbps")),
        _fmt(result.get("upload_mbps")),
        _fmt(result.get("ping_ms")),
        _fmt(result.get("jitter_ms")),
        _fmt(result.get("packet_loss_pct")),
        result.get("external_ip") or "-",
        str(result.get("tested_at", "-")),
    ]


def render_table(results: dict[str, dict[str, Any]]) -> str:
    """Render a fixed-width table of per-server speedtest results."""
    if not results:
        return "No speedtest results yet. Run: vpn server speedtest --all"

    header = [f"{h} ({u})" if u else h for h, u in zip(HEADERS, UNITS)]
    rows = [_row(name, results[name]) for name in sorted(results)]
    widths = [
        max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))
    ]

    def line(cells: list[str]) -> str:
        return " ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)).rstrip()

    out = [line(header), "-" * (sum(widths) + len(widths) - 1)]
    out.extend(line(r) for r in rows)
    return "\n".join(out)

