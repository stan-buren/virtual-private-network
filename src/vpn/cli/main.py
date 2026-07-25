"""VPN CLI entry point — Click group for server, status, and bypass commands.

Communicates with the daemon via JSON-RPC over Unix socket (/var/run/vpn.sock).
"""

from __future__ import annotations

import click

from vpn.cli.ipc import call as ipc_call


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


# ── emergency-reset ──────────────────────────────────────────────────────────

@cli.command()
def emergency_reset() -> None:
    """Emergency reset: wipe all rules, routes, tun0. Use with caution."""
    click.echo("Emergency reset — not yet implemented via IPC. Run locally if needed.")


if __name__ == "__main__":
    cli()
