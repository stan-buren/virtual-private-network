"""VPN CLI entry point — Click group for server, status, and bypass commands.

Communicates with the daemon via JSON-RPC over Unix socket (/var/run/vpn.sock).
"""

from __future__ import annotations

import shlex
import sys
import threading
import time
from datetime import datetime, timezone

import click

from vpn.adapters.system.filesystem import FilesystemAdapter
from vpn.adapters.system.shell import ShellAdapter
from vpn.cli.ipc import call as ipc_call
from vpn.config.paths import PROJECT_ROOT, load_paths_config
from vpn.core.speedtest import (
    SpeedtestError,
    SpeedtestRunner,
    SpeedtestStore,
    render_table,
)


@click.group()
@click.version_option(version="0.1.0", prog_name="vpn")
def cli() -> None:
    """VPN Orchestrator — manage sing-box tunnels, routing, and health."""


# ── server ───────────────────────────────────────────────────────────────────

@cli.group()
def server() -> None:
    """Manage VPN servers."""


@server.command("list")
def server_list() -> None:
    """List all available VPN servers."""
    servers = ipc_call("server.list")
    click.echo(f"{'Name':20} {'Country':5} {'Host':18} {'Port':5}")
    click.echo("-" * 50)
    for s in servers:
        click.echo(f"{s['name']:20} {s['country']:5} {s['host']:18} {s['port']:<5}")


@server.command("current")
def server_current() -> None:
    """Show the currently active VPN server."""
    result = ipc_call("server.current")
    click.echo(result)


@server.command("change")
@click.argument("name", required=True)
def server_change(name: str) -> None:
    """Switch to a different VPN server. Usage: vpn server change barguzin"""
    result = ipc_call("server.change", {"name": name})
    click.echo(f"Switched to: {result}")


# ── server speedtest ─────────────────────────────────────────────────────────

def _cache_dir() -> str:
    """Resolve the cache directory (where speedtest results live)."""
    try:
        rel = load_paths_config(PROJECT_ROOT).get("cache_dir", "cache")
    except Exception:
        rel = "cache"
    return str(PROJECT_ROOT / rel)


def _store() -> SpeedtestStore:
    return SpeedtestStore(_cache_dir())


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _echo(text: str = "", *, err: bool = False) -> None:
    """Write a line and flush so progress is visible in real time."""
    click.echo(text, err=err)
    (sys.stderr if err else sys.stdout).flush()


def _tunnel_ready() -> bool:
    """True when outbound HTTPS works through the tunnel."""
    res = ShellAdapter().run(
        "curl -s -m 8 -o /dev/null -w '%{http_code}' https://ifconfig.me/ip",
        capture=True,
        timeout=12,
    )
    return bool(res and res.returncode == 0 and res.stdout.strip().startswith("200"))


def _switch_and_wait(name: str, attempts: int = 25) -> None:
    """Switch the active server and wait until the tunnel carries traffic."""
    ipc_call("server.change", {"name": name})
    for _ in range(attempts):
        if _tunnel_ready():
            return
        time.sleep(1)
    raise SpeedtestError(f"tunnel not ready after switching to {name}")


def _run_with_heartbeat(runner: SpeedtestRunner) -> dict:
    """Run the speedtest, printing a dot every few seconds to show liveness."""
    done = threading.Event()

    def beat() -> None:
        while not done.wait(5):
            click.echo(".", nl=False)
            sys.stdout.flush()

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        return runner.run()
    finally:
        done.set()
        thread.join(timeout=2)
        click.echo("")


def _resolve_targets(items: tuple[str, ...], known: dict[str, dict]) -> list[str]:
    """Expand repeatable/comma-separated --server values, dedupe, and validate."""
    resolved: list[str] = []
    for item in items:
        for part in item.split(","):
            part = part.strip()
            if part and part not in resolved:
                resolved.append(part)
    unknown = [name for name in resolved if name not in known]
    if unknown:
        raise SpeedtestError("unknown server(s): " + ", ".join(unknown))
    return resolved


def _run_speedtest(targets: list[str] | None) -> int:
    """Run speedtests for the given servers (None = all) and print the table."""
    store = _store()
    if not store.acquire():
        _echo("Error: a speedtest run is already in progress.", err=True)
        return 1
    try:
        servers = ipc_call("server.list")
        by_name = {s["name"]: s for s in servers}
        if targets is None:
            names = sorted(by_name)
        else:
            try:
                names = _resolve_targets(tuple(targets), by_name)
            except SpeedtestError as exc:
                _echo(f"Error: {exc}.", err=True)
                _echo("Known servers: " + ", ".join(sorted(by_name)), err=True)
                return 1
        if not names:
            _echo("No servers to test.", err=True)
            return 1

        try:
            original = (ipc_call("server.current") or {}).get("server")
        except Exception:
            original = None

        runner = SpeedtestRunner(ShellAdapter())
        started = _now()
        total = len(names)
        _echo(f"Speedtest: {total} server(s) — {', '.join(names)}")

        for idx, name in enumerate(names, 1):
            country = by_name[name].get("country", "-")
            store.write_status(
                {
                    "running": True,
                    "current": name,
                    "targets": names,
                    "started_at": started,
                }
            )
            entry: dict = {"country": country, "tested_at": _now()}
            _echo(f"[{idx}/{total}] {name} ({country}): switching tunnel ...")
            try:
                _switch_and_wait(name)
                _echo(f"[{idx}/{total}] {name}: speedtest running ...", )
                entry.update(_run_with_heartbeat(runner))
            except Exception as exc:
                entry["error"] = str(exc)
            entry["tested_at"] = _now()
            store.write_result(name, entry)
            if entry.get("error"):
                _echo(f"[{idx}/{total}] {name}: ERROR — {entry['error']}", err=True)
            else:
                _echo(
                    f"[{idx}/{total}] {name}: down={entry['download_mbps']} "
                    f"up={entry['upload_mbps']} ping={entry['ping_ms']} "
                    f"jitter={entry['jitter_ms']} ip={entry['external_ip']}"
                )

        if original and original in by_name and original not in names:
            _echo(f"Restoring active server: {original} ...")
            try:
                _switch_and_wait(original)
            except Exception as exc:
                _echo(f"warning: could not restore {original}: {exc}", err=True)

    finally:
        try:
            store.write_status(
                {"running": False, "current": None, "finished_at": _now()}
            )
        except Exception:
            pass
        store.release()
    _echo("")
    _echo(render_table(store.all_results()))
    return 0


def _view_speedtest(max_wait: int = 3600) -> int:
    """Print the results table, waiting while a run is in progress."""
    store = _store()
    if store.is_running():
        current = store.read_status().get("current") or "?"
        _echo(f"speedtest in progress (current: {current}); waiting ...", err=True)
    waited = 0
    while store.is_running() and waited < max_wait:
        time.sleep(1)
        waited += 1
    _echo(render_table(store.all_results()))
    return 0


@server.group("speedtest", invoke_without_command=True)
@click.option("--all", "run_all", is_flag=True, help="Run the speedtest for every server.")
@click.option(
    "--server",
    "servers",
    multiple=True,
    metavar="NAME",
    help="Server(s) to test: repeat --server or pass comma-separated names.",
)
@click.pass_context
def server_speedtest(ctx: click.Context, run_all: bool, servers: tuple[str, ...]) -> None:
    """Measure speed, ping, jitter and loss per server (Ookla Speedtest CLI).

    The active server is switched for each test and restored afterwards.

    Examples:
      vpn server speedtest --all
      vpn server speedtest --server <name> --server <name>
      vpn server speedtest --server <name>,<name>
      vpn server speedtest view
    """
    if ctx.invoked_subcommand is not None:
        return
    if run_all and servers:
        raise click.UsageError("use either --all or --server, not both")
    if not run_all and not servers:
        raise click.UsageError(
            "specify --all or --server NAME (see: vpn server speedtest --help)"
        )
    ctx.exit(_run_speedtest(None if run_all else list(servers)))


@server_speedtest.command("view")
def server_speedtest_view() -> None:
    """Show the latest speedtest table (waits for a run in progress)."""
    raise SystemExit(_view_speedtest())


@cli.group("config")
def config_group() -> None:
    """Manage the provider configuration (subscription)."""


@config_group.command("update")
def config_update() -> None:
    """Download the provider subscription and make it the source of truth."""
    from vpn.config.config_loader import get_subscription_config
    from vpn.core.subscription import SubscriptionError, SubscriptionUpdater

    try:
        url = get_subscription_config().url
    except Exception as exc:
        _echo(f"Error: subscription config unavailable: {exc}", err=True)
        raise SystemExit(1)
    if not url:
        _echo("Error: no subscription URL configured (config/subscription.yaml).", err=True)
        raise SystemExit(1)

    _echo(f"Fetching subscription: {url}")
    res = ShellAdapter().run(
        f"curl -fsSL -m 60 {shlex.quote(url)}", capture=True, timeout=75
    )
    if res is None or res.returncode != 0:
        code = None if res is None else res.returncode
        _echo(f"Error: download failed (curl exit {code}).", err=True)
        raise SystemExit(1)

    try:
        paths = load_paths_config(PROJECT_ROOT)
    except Exception:
        paths = {}
    target = str(PROJECT_ROOT / paths.get("profile_keys", "data/profile.json"))
    legacy = [
        str(PROJECT_ROOT / "data" / "profile_keys_*.json"),
        str(PROJECT_ROOT / "data" / "profile*.json"),
    ]
    fs = FilesystemAdapter()
    try:
        baseline = fs.read_json(str(PROJECT_ROOT / "config" / "singbox_baseline.json"))
    except Exception:
        baseline = {}
    try:
        summary = SubscriptionUpdater(fs, target, legacy, baseline).apply(res.stdout)
    except SubscriptionError as exc:
        _echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    _echo(f"Profile updated: {summary['target']} ({summary['server_count']} servers)")
    if summary["removed"]:
        _echo("Removed legacy profiles: " + ", ".join(summary["removed"]))

    _echo("Reloading daemon onto the new profile ...")
    try:
        result = ipc_call("config.reload")
        _echo(
            f"Active server: {result.get('server')} "
            f"({result.get('count')} servers available)"
        )
    except Exception as exc:
        _echo(f"Warning: daemon reload failed: {exc}", err=True)


# ── status ───────────────────────────────────────────────────────────────────

@cli.command()
def status() -> None:
    """Show current daemon status."""
    result = ipc_call("status")
    for k, v in result.items():
        click.echo(f"{k}: {v}")


# ── restart ──────────────────────────────────────────────────────────────────

@cli.command()
def restart() -> None:
    """Force a full daemon restart."""
    result = ipc_call("restart")
    click.echo(result.get("status", "ok"))


# ── bypass ───────────────────────────────────────────────────────────────────

@cli.group()
def bypass() -> None:
    """Manage the VPN bypass list."""


@bypass.command("list")
def bypass_list() -> None:
    """Show current bypass domains."""
    domains = ipc_call("bypass.list")
    for d in domains:
        click.echo(d)


@bypass.command("add")
@click.option("--domain", "-d", required=True, help="Domain to bypass VPN")
def bypass_add(domain: str) -> None:
    """Add a domain to the bypass list."""
    result = ipc_call("bypass.add", {"domain": domain})
    click.echo(f"Bypass list now: {result}")


@bypass.command("remove")
@click.option("--domain", "-d", required=True, help="Domain to remove")
def bypass_remove(domain: str) -> None:
    """Remove a domain from the bypass list."""
    result = ipc_call("bypass.remove", {"domain": domain})
    click.echo(f"Bypass list now: {result}")


# ── stop / start ─────────────────────────────────────────────────────────────

@cli.command()
def stop() -> None:
    """Stop VPN: wipe all rules, routes, tun0. Traffic goes direct."""
    result = ipc_call("stop")
    click.echo(result.get("status", "error"))


@cli.command()
def start() -> None:
    """Start VPN: bootstrap tunnel, routing, firewall."""
    result = ipc_call("start")
    click.echo(result.get("status", "error"))


# ── route ────────────────────────────────────────────────────────────────────

@cli.group()
def route() -> None:
    """Manage forced-VPN routes (domains forced through VPN tunnel)."""


@route.command("list")
def route_list() -> None:
    """Show current forced-VPN routes."""
    result = ipc_call("route.list")
    click.echo("Domains:")
    for d in result.get("domains", []):
        click.echo("  " + d)
    click.echo("Wildcards:")
    for w in result.get("wildcards", []):
        click.echo("  " + w)
    click.echo("Subnets:")
    for s in result.get("subnets", []):
        click.echo("  " + s)


@route.command("add")
@click.option("--domain", "-d", default=None, help="Domain to force through VPN")
@click.option("--wildcard", "-w", default=None, help="Wildcard pattern (e.g. *.openai.com)")
@click.option("--subnet", "-s", default=None, help="CIDR subnet to force through VPN")
def route_add(domain: str | None, wildcard: str | None, subnet: str | None) -> None:
    """Force a domain, wildcard, or subnet through the VPN tunnel."""
    params: dict[str, str] = {}
    if domain:
        params["domain"] = domain
    elif wildcard:
        params["wildcard"] = wildcard
    elif subnet:
        params["subnet"] = subnet
    else:
        click.echo("Error: specify --domain, --wildcard, or --subnet")
        return
    result = ipc_call("route.add", params)
    click.echo(result)


@route.command("remove")
@click.option("--domain", "-d", default=None, help="Domain to remove")
@click.option("--wildcard", "-w", default=None, help="Wildcard pattern to remove")
@click.option("--subnet", "-s", default=None, help="CIDR subnet to remove")
def route_remove(domain: str | None, wildcard: str | None, subnet: str | None) -> None:
    """Remove a forced-VPN route."""
    params: dict[str, str] = {}
    if domain:
        params["domain"] = domain
    elif wildcard:
        params["wildcard"] = wildcard
    elif subnet:
        params["subnet"] = subnet
    else:
        click.echo("Error: specify --domain, --wildcard, or --subnet")
        return
    result = ipc_call("route.remove", params)
    click.echo(result)


if __name__ == "__main__":
    cli()

