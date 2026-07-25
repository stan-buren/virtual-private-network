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
