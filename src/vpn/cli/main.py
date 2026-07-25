"""VPN CLI entry point — Click group for server, status, logs, and bypass commands."""

from __future__ import annotations

import click


@click.group()
@click.version_option(version="0.1.0", prog_name="vpn")
def cli() -> None:
    """VPN Orchestrator — manage sing-box tunnels, routing, and health."""


@cli.group()
def server() -> None:
    """Manage VPN servers."""


@server.command("list")
def server_list() -> None:
    """List all available VPN servers."""
    click.echo("Server list (CLI stub — daemon connection required)")


@server.command("current")
def server_current() -> None:
    """Show the currently active VPN server."""
    click.echo("Current server (CLI stub — daemon connection required)")


@server.command("change")
@click.option("--name", "-n", required=True, help="Server short name (e.g. barguzin)")
def server_change(name: str) -> None:
    """Switch to a different VPN server."""
    click.echo("Switching to server: %s (CLI stub — daemon connection required)" % name)


@cli.command()
def status() -> None:
    """Show current daemon status."""
    click.echo("VPN status (CLI stub — daemon connection required)")


@cli.command()
def restart() -> None:
    """Force a full daemon restart."""
    click.echo("Restarting (CLI stub — daemon connection required)")


@cli.command()
def emergency_reset() -> None:
    """Emergency reset: wipe all rules, routes, tun0."""
    click.echo("Emergency reset (CLI stub — daemon connection required)")


@cli.group()
def bypass() -> None:
    """Manage the VPN bypass list."""


@bypass.command("list")
def bypass_list() -> None:
    """Show current bypass list."""
    click.echo("Bypass list (CLI stub — daemon connection required)")


@bypass.command("add")
@click.option("--domain", "-d", help="Domain to bypass VPN")
@click.option("--subnet", "-s", help="CIDR subnet to bypass VPN")
def bypass_add(domain: str | None, subnet: str | None) -> None:
    """Add a domain or subnet to the bypass list."""
    target = domain or subnet
    click.echo("Adding to bypass: %s (CLI stub — daemon connection required)" % target)


@bypass.command("remove")
@click.option("--domain", "-d", help="Domain to remove")
@click.option("--subnet", "-s", help="CIDR subnet to remove")
def bypass_remove(domain: str | None, subnet: str | None) -> None:
    """Remove a domain or subnet from the bypass list."""
    target = domain or subnet
    click.echo("Removing from bypass: %s (CLI stub — daemon connection required)" % target)


if __name__ == "__main__":
    cli()
