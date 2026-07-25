"""VpnOrchestrator — thin sequencer that wires core services and runs bootstrap.

Contains zero business logic — all decisions are delegated to the injected
services. The orchestrator only knows *when* to call what, not *how*.
"""

from __future__ import annotations

import asyncio
import logging
import time

from vpn.core.events import EventType, VpnEvent
from vpn.core.firewall.mss import MssClamp
from vpn.core.firewall.nat import NatManager
from vpn.core.firewall.sysctl import SysctlManager
from vpn.core.notification.telegram import TelegramNotifier
from vpn.core.ports import ShellPort, VpnProviderPort
from vpn.core.routing.bypass_loader import BypassLoader
from vpn.core.routing.route_table import RouteTable
from vpn.core.routing.rule_manager import PRIO_DNS_START, PRIO_LAN_START, RuleManager
from vpn.core.routing.tun_interface import TunInterface
from vpn.core.ru_updater.updater import RuSubnetUpdater
from vpn.core.server_manager.deployer import ConfigDeployer
from vpn.core.state_machine.context import RuntimeContext
from vpn.core.topology.discovery import ServerIpResolver, TopologyDiscovery
from vpn.core.tunnel.tun2socks import Tun2SocksManager
from vpn.config.core.app import AppConfig
from vpn.config.core.bypass import BypassConfig
from vpn.config.core.network import NetworkConfig
from vpn.config.core.tunnel import TunnelConfig
from vpn.config.core.vpn_routes import VpnRoutesConfig

logger = logging.getLogger("vpn")


class VpnOrchestrator:
    """Thin sequencer — wires core services, runs bootstrap, no business logic.

    Receives all services via constructor injection and orchestrates the
    multi-step bootstrap sequence when :meth:`bootstrap` is called.
    """

    def __init__(
        self,
        *,
        deployer: ConfigDeployer,
        topology_discovery: TopologyDiscovery,
        resolver: ServerIpResolver,
        tun: TunInterface,
        rules: RuleManager,
        route_table: RouteTable,
        bypass_loader: BypassLoader,
        nat: NatManager,
        mss: MssClamp,
        sysctl_mgr: SysctlManager,
        tun2socks: Tun2SocksManager,
        provider: VpnProviderPort,
        notifier: TelegramNotifier,
        ru_updater: RuSubnetUpdater,
        shell: ShellPort,
        app_cfg: AppConfig,
        net_cfg: NetworkConfig,
        tunnel_cfg: TunnelConfig,
        bypass_cfg: BypassConfig,
        vpn_routes_cfg: VpnRoutesConfig,
        paths: dict[str, str],
    ) -> None:
        self._deployer = deployer
        self._topology_discovery = topology_discovery
        self._resolver = resolver
        self._tun = tun
        self._rules = rules
        self._route_table = route_table
        self._bypass_loader = bypass_loader
        self._nat = nat
        self._mss = mss
        self._sysctl_mgr = sysctl_mgr
        self._tun2socks = tun2socks
        self._provider = provider
        self._notifier = notifier
        self._ru_updater = ru_updater
        self._shell = shell
        self._app_cfg = app_cfg
        self._net_cfg = net_cfg
        self._tunnel_cfg = tunnel_cfg
        self._bypass_cfg = bypass_cfg
        self._vpn_routes_cfg = vpn_routes_cfg
        self._paths = paths
        self._ru_updater_task: asyncio.Task[None] | None = None

    async def bootstrap(self, ctx: RuntimeContext, events: asyncio.Queue[VpnEvent]) -> None:
        """Execute the full bootstrap sequence.

        Steps:
            1. Deploy sing-box config
            2. Discover network topology
            3. Configure routing (TUN, server/DNS/LAN bypasses, route table)
            4. Apply firewall rules (NAT, MSS, sysctl)
            5. Start tunnel and background tasks
            6. Post BOOTSTRAP_DONE event
        """
        logger.info("=== VPN Bootstrap Sequence ===")

        # 1. Deploy config
        logger.info("[1/6] Deploying sing-box configuration")
        self._deployer.deploy()

        # 2. Discover topology
        logger.info("[2/6] Discovering network topology")
        topology = self._topology_discovery.discover()
        ctx.gateway = topology.gateway
        ctx.interface = topology.interface

        # 3. Routing
        logger.info("[3/6] Configuring routing")
        self._tun.create()

        profile_path = self._paths.get("profile_keys", "")
        server_ips = self._resolver.resolve_all(profile_path, self._shell)

        for ip in server_ips:
            self._rules.add_server_bypass(ip)

        for i, dns_ip in enumerate(self._net_cfg.dns_servers):
            self._rules.add_dns_bypass(dns_ip, priority=PRIO_DNS_START + i)

        for i, subnet in enumerate(self._net_cfg.lan_subnets):
            self._rules.add_lan_bypass(subnet, priority=PRIO_LAN_START + i)

        ru_cache_path = self._paths.get("ru_subnets", "cache/ru-subnets.txt")
        routes = self._bypass_loader.load_all(
            ru_cache_path=ru_cache_path,
            bypass_domains=self._bypass_cfg.domains,
            bypass_subnets=self._bypass_cfg.subnets,
            vpn_domains=self._vpn_routes_cfg.domains,
            vpn_wildcards=self._vpn_routes_cfg.wildcards,
            vpn_subnets=self._vpn_routes_cfg.subnets,
            gateway=topology.gateway,
            interface=topology.interface,
            table_id=self._app_cfg.table_id,
        )
        self._route_table.load_batch(routes, self._app_cfg.table_id)
        self._rules.add_torrent_bypass()
        self._rules.add_catchall(self._app_cfg.table_id)
        self._route_table.set_default(self._app_cfg.table_id)

        # 4. Firewall
        logger.info("[4/6] Applying firewall rules")
        self._nat.apply(topology.interface)
        self._mss.apply()
        self._sysctl_mgr.enable_ip_forward()
        self._sysctl_mgr.disable_ipv6_wan()

        # 5. Start tunnel + background tasks
        logger.info("[5/6] Starting tunnel and background tasks")
        proxy_url = "socks5://%s:%d" % (self._tunnel_cfg.socks5_host, self._tunnel_cfg.socks5_port)
        ctx.tun2socks = self._tun2socks.start(proxy_url)
        ctx.startup_time = time.time()
        servers = self._provider.list_servers()
        ctx.active_server = servers[0].name if servers else "unknown"
        self._ru_updater_task = asyncio.create_task(self._ru_updater.run_forever())

        # 6. Signal done
        logger.info("[6/6] Bootstrap complete — posting BOOTSTRAP_DONE")
        await events.put(VpnEvent(EventType.BOOTSTRAP_DONE))
