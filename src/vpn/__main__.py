"""VPN Daemon entry point — wires adapters, configs, and starts the state machine.

Usage:
    python -m vpn          # Start the daemon
    vpn-internal server list  # CLI commands (from inside container)
"""

from __future__ import annotations

import asyncio
import logging
import signal

from vpn.adapters.akonit.provider import AkonitProvider
from vpn.adapters.http.urllib_http import UrllibHttpAdapter
from vpn.adapters.system.filesystem import FilesystemAdapter
from vpn.adapters.system.shell import ShellAdapter
from vpn.adapters.system.subprocess import SubprocessAdapter
from vpn.config.config_loader import (
    get_app_config,
    get_bypass_config,
    get_health_config,
    get_network_config,
    get_notification_config,
    get_tunnel_config,
    get_vpn_routes_config,
)
from vpn.config.paths import PROJECT_ROOT, load_paths_config
from vpn.core.events import EventType, VpnEvent
from vpn.core.firewall.mss import MssClamp
from vpn.core.firewall.nat import NatManager
from vpn.core.firewall.sysctl import SysctlManager
from vpn.core.health.checker import HealthChecker
from vpn.core.notification.telegram import TelegramNotifier
from vpn.core.orchestrator import VpnOrchestrator
from vpn.core.routing.bypass_loader import BypassLoader
from vpn.core.routing.route_table import RouteTable
from vpn.core.routing.rule_manager import RuleManager
from vpn.core.routing.tun_interface import TunInterface
from vpn.core.ru_updater.updater import RuSubnetUpdater
from vpn.core.server_manager.deployer import ConfigDeployer
from vpn.core.server_manager.switcher import ServerSwitcher
from vpn.core.state_machine.machine import VpnStateMachine
from vpn.core.state_machine.states.bootstrapping import BootstrappingState
from vpn.core.topology.discovery import DnsResolver, ServerIpResolver, TopologyDiscovery
from vpn.core.tunnel.tun2socks import Tun2SocksManager
from vpn.logger import setup_logging

logger = logging.getLogger("vpn")


async def _main() -> None:
    """Wire adapters, create services, start state machine."""
    setup_logging(level=logging.DEBUG, use_json=False)
    logger.info("VPN Daemon starting — project root: %s", PROJECT_ROOT)

    # ── Load configs ──────────────────────────────────────────────────────
    paths = load_paths_config(PROJECT_ROOT)
    app_cfg = get_app_config()
    net_cfg = get_network_config()
    health_cfg = get_health_config()
    tunnel_cfg = get_tunnel_config()
    bypass_cfg = get_bypass_config()
    vpn_routes_cfg = get_vpn_routes_config()
    notify_cfg = get_notification_config()

    logger.info("App config: provider=%s, table=%s", app_cfg.provider, app_cfg.table_id)

    # ── Wire adapters ─────────────────────────────────────────────────────
    shell = ShellAdapter()
    fs = FilesystemAdapter()
    subproc = SubprocessAdapter()
    http_adapter = UrllibHttpAdapter()

    # ── Wire provider ─────────────────────────────────────────────────────
    profile_path = str(PROJECT_ROOT / paths.get("profile_keys", "data/profile_keys_akonit_24_07_2026.json"))
    provider = AkonitProvider(profile_path)

    # ── Wire core services ────────────────────────────────────────────────
    topology_discovery = TopologyDiscovery(shell)
    dns_resolver = DnsResolver()
    server_ip_resolver = ServerIpResolver(fs, dns_resolver)
    tun = TunInterface(shell, net_cfg.tun_address, net_cfg.tun_mtu)
    rules = RuleManager(shell)
    route_table = RouteTable(shell)
    bypass_loader = BypassLoader(shell, fs, dns_resolver)
    nat = NatManager(shell, app_cfg.chain_name)
    mss = MssClamp(shell, net_cfg.mss_clamp)
    sysctl_mgr = SysctlManager(shell)
    tun2socks = Tun2SocksManager(subproc)
    config_deployer = ConfigDeployer(
        provider, fs, profile_path, paths.get("sing_box_config", "/etc/sing-box/config.json")
    )
    server_switcher = ServerSwitcher(
        provider, fs, shell, paths.get("sing_box_config", "/etc/sing-box/config.json")
    )
    health_checker = HealthChecker(
        shell,
        targets=health_cfg.targets,
        user_agents=health_cfg.user_agents,
        interval_range=(health_cfg.check_interval_min, health_cfg.check_interval_max),
        curl_timeout=health_cfg.curl_timeout,
    )
    telegram = TelegramNotifier()
    ru_updater = RuSubnetUpdater(
        fs, str(PROJECT_ROOT / paths.get("ru_subnets", "cache/ru-subnets.txt"))
    )

    # ── Wire orchestrator ─────────────────────────────────────────────────
    orchestrator = VpnOrchestrator(
        deployer=config_deployer,
        topology_discovery=topology_discovery,
        resolver=server_ip_resolver,
        tun=tun,
        rules=rules,
        route_table=route_table,
        bypass_loader=bypass_loader,
        nat=nat,
        mss=mss,
        sysctl_mgr=sysctl_mgr,
        tun2socks=tun2socks,
        provider=provider,
        notifier=telegram,
        ru_updater=ru_updater,
        shell=shell,
        subprocess=subproc,
        app_cfg=app_cfg,
        net_cfg=net_cfg,
        tunnel_cfg=tunnel_cfg,
        bypass_cfg=bypass_cfg,
        vpn_routes_cfg=vpn_routes_cfg,
        paths=paths,
    )

    # ── Create state machine ──────────────────────────────────────────────
    machine = VpnStateMachine(
        BootstrappingState,
        provider=provider,
        switcher=server_switcher,
        resolver=server_ip_resolver,
        rules=rules,
        shell=shell,
        bypass_cfg=bypass_cfg,
        vpn_routes_cfg=vpn_routes_cfg,
        dns_resolver=dns_resolver,
        paths=paths,
    )
    ctx = machine.context
    events = machine._event_queue
    machine._orchestrator = orchestrator

    # Bootstrap is triggered by BootstrappingState.on_enter() — no external task needed

    # ── Start signal handlers ─────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(events.put(VpnEvent(EventType.SHUTDOWN_REQUESTED))),
        )

    # ── Run state machine event loop ──────────────────────────────────────
    await machine.run()


def main() -> None:
    """Synchronous entry point."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
