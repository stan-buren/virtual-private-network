"""VpnOrchestrator — thin sequencer that wires core services and runs bootstrap.

Contains zero business logic — all decisions are delegated to the injected
services. The orchestrator only knows *when* to call what, not *how*.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from vpn.core import obs
from vpn.core.events import EventType, VpnEvent
from vpn.core.firewall.mss import MssClamp
from vpn.core.firewall.nat import NatManager
from vpn.core.firewall.sysctl import SysctlManager
from vpn.core.health.process_watcher import ProcessWatcher
from vpn.core.ports import ShellPort, SubprocessPort, VpnProviderPort
from vpn.logger.exceptions import VpnConnectionError
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
from vpn.config.paths import PROJECT_ROOT

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
        watcher: ProcessWatcher,
        shell: ShellPort,
        subprocess: SubprocessPort,
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
        self._watcher = watcher
        self._shell = shell
        self._app_cfg = app_cfg
        self._net_cfg = net_cfg
        self._tunnel_cfg = tunnel_cfg
        self._bypass_cfg = bypass_cfg
        self._vpn_routes_cfg = vpn_routes_cfg
        self._paths = paths
        self._subprocess = subprocess
        self._tunnel_lock = asyncio.Lock()

    async def bootstrap(self, ctx: RuntimeContext, events: asyncio.Queue[VpnEvent]) -> None:
        """Bring the tunnel up once, pinned to one explicit server.

        No probing, no rotation and no recovery: resolve the operator's chosen
        server, deploy exactly that config, install routing and start the
        processes. The daemon never picks a different node on its own.
        """
        started = obs.now()
        logger.info("=== VPN Bootstrap Sequence ===")
        obs.emit("SYS", "info", "bootstrap.start", cost="none")

        # 0. Remove leftovers from an unclean shutdown.
        await self.teardown_network()

        # 1. Resolve the operator's server and pin the config to it.
        server = self._resolve_active_server()
        ctx.active_server = server
        step = obs.now()
        if not self._pin_config_to_server(server):
            obs.emit(
                "CFG", "fail", "config.deploy", cost="none",
                latency_ms=(obs.now() - step) * 1000,
                error_class="config_deploy_failed", server=server,
            )
            raise VpnConnectionError("cannot deploy sing-box config for %r" % server)
        obs.emit(
            "CFG", "ok", "config.deploy", cost="none",
            latency_ms=(obs.now() - step) * 1000, server=server,
            config=self._paths.get("sing_box_config", "/etc/sing-box/config.json"),
        )

        # 2. sing-box
        step = obs.now()
        self.start_singbox(ctx)
        await self._wait_for_socks_port()
        obs.emit(
            "L0", "ok", "process.start", cost="none",
            latency_ms=(obs.now() - step) * 1000, process="sing-box",
            pid=getattr(ctx.singbox, "pid", None),
        )

        # 3. Topology
        topology = self._topology_discovery.discover()
        ctx.gateway = topology.gateway
        ctx.interface = topology.interface
        obs.emit(
            "SYS", "ok", "topology.discover", cost="none",
            gateway=topology.gateway, interface=topology.interface,
        )

        # 4. Routing
        step = obs.now()
        self._tun.create()
        routed = self.ensure_routing(ctx, reload_routes=True)
        obs.emit(
            "L2", "ok" if routed else "fail", "routing.assert",
            cost="route-change", latency_ms=(obs.now() - step) * 1000,
            error_class=None if routed else "catchall_missing",
            routes=self._routing_route_count(self._app_cfg.table_id),
        )

        # 5. Firewall
        step = obs.now()
        self._nat.apply(topology.interface)
        self._mss.apply()
        self._sysctl_mgr.enable_ip_forward()
        self._sysctl_mgr.disable_ipv6_wan()
        obs.emit(
            "L2", "ok", "firewall.apply", cost="route-change",
            latency_ms=(obs.now() - step) * 1000, interface=topology.interface,
        )

        # 6. tun2socks
        step = obs.now()
        self.start_tun2socks(ctx)
        ctx.startup_time = time.time()
        obs.emit(
            "L0", "ok", "process.start", cost="none",
            latency_ms=(obs.now() - step) * 1000, process="tun2socks",
            pid=getattr(ctx.tun2socks, "pid", None),
        )

        self._ru_updater_task = asyncio.create_task(self._ru_updater.run_forever())

        # 7. One verification, for the log only. It never changes anything.
        step = obs.now()
        ok = await self.verify_tunnel()
        obs.emit(
            "L1", "ok" if ok else "fail", "tunnel.verify", cost="none",
            latency_ms=(obs.now() - step) * 1000,
            error_class=None if ok else "no_traffic_through_socks",
            server=server,
        )

        obs.emit(
            "SYS", "ok", "bootstrap.done", cost="none",
            latency_ms=(obs.now() - started) * 1000, server=server, verified=ok,
        )
        await events.put(VpnEvent(EventType.BOOTSTRAP_DONE))

    # ── Manual server selection ───────────────────────────────────────────

    def _active_server_file(self) -> str:
        """Path of the persisted manual selection."""
        return str(
            Path(PROJECT_ROOT) / self._paths.get("cache_dir", "cache") / "active_server"
        )

    def _resolve_active_server(self) -> str:
        """Return the operator's server: cache file, then config, then warn."""
        servers = {s.name for s in self._provider.list_servers()}
        candidates: list[tuple[str, str]] = []
        path = self._active_server_file()
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as handle:
                    candidates.append((handle.read().strip(), "cache"))
        except OSError:
            logger.warning("Cannot read %s", path, exc_info=True)
        if self._app_cfg.active_server:
            candidates.append((self._app_cfg.active_server.strip(), "config"))

        for name, source in candidates:
            if name and name in servers:
                obs.emit("CFG", "ok", "server.resolve", server=name, source=source)
                return name
            if name:
                obs.emit(
                    "CFG", "warn", "server.resolve",
                    error_class="unknown_server", server=name, source=source,
                )

        if not servers:
            raise VpnConnectionError("provider profile has no servers")
        fallback = sorted(servers)[0]
        obs.emit(
            "CFG", "warn", "server.resolve", error_class="no_active_server",
            server=fallback, hint="run: vpn server change <name>",
        )
        return fallback

    def _pin_config_to_server(self, name: str) -> bool:
        """Write a sing-box config whose final outbound is exactly *name*."""
        try:
            config = self._provider.build_singbox_config(name)
        except Exception:
            logger.exception("Cannot build config for %s", name)
            return False
        dest = self._paths.get("sing_box_config", "/etc/sing-box/config.json")
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as handle:
                handle.write(config)
        except OSError:
            logger.exception("Cannot write %s", dest)
            return False
        return True

    def persist_active_server(self, name: str) -> None:
        """Remember the operator's choice across container recreations."""
        path = self._active_server_file()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(name.strip() + "\n")
            obs.emit("CFG", "ok", "server.persist", server=name, path=path)
        except OSError as exc:
            obs.emit(
                "CFG", "warn", "server.persist",
                error_class="persist_failed", error=str(exc)[:200],
            )

    # ── Policy routing: the single source of truth ────────────────────────

    BATCH_ROUTE_MIN = 100

    def ensure_routing(self, ctx: RuntimeContext, reload_routes: bool = False) -> bool:
        """(Re)assert the complete policy-routing state; safe to call repeatedly.

        Bootstrap, a server switch and every recovery rung must finish here.
        The ip rules and the table-100 routes are plain kernel state: a netplan
        apply, an interface reconfiguration or a DHCP lease renewal wipes them
        without a trace, and the SOCKS inbound keeps answering while the host
        sends every packet out of the physical uplink.

        Args:
            ctx: Runtime context carrying the discovered topology.
            reload_routes: Force a reload of the bypass route batch even when
                the table still looks populated (used by a fresh bootstrap).

        Returns:
            True when the catch-all rule is in place, i.e. host traffic can
            actually reach the tunnel.
        """
        table_id = self._app_cfg.table_id
        profile_path = self._paths.get("profile_keys", "")
        server_ips = self._resolver.resolve_all(profile_path, self._shell)

        self._rules.clear_server_bypasses()
        for ip in server_ips:
            self._rules.add_server_bypass(ip)

        for i, dns_ip in enumerate(self._net_cfg.dns_servers):
            self._rules.add_dns_bypass(dns_ip, priority=PRIO_DNS_START + i)

        for i, subnet in enumerate(self._net_cfg.lan_subnets):
            self._rules.add_lan_bypass(subnet, priority=PRIO_LAN_START + i)

        self._rules.add_torrent_bypass()
        self._route_table.set_default(table_id)
        self._ensure_bypass_routes(ctx, force=reload_routes)

        ok = self._rules.add_catchall(table_id)
        if ok:
            logger.info(
                "Policy routing asserted: %d server bypasses, table %s, %d routes",
                len(server_ips),
                table_id,
                self._routing_route_count(table_id),
            )
        return ok

    def _routing_route_count(self, table_id: str) -> int:
        """Return how many routes are currently present in *table_id*."""
        result = self._shell.run("ip route show table %s" % table_id, capture=True)
        text = (result.stdout or "") if result is not None else ""
        return len([line for line in text.splitlines() if line.strip()])

    def _ensure_bypass_routes(self, ctx: RuntimeContext, force: bool = False) -> None:
        """Reload the table-100 route batch when it is missing or forced.

        The batch carries the RU bypass subnets and the per-domain VPN routes.
        Losing it is survivable but wrong: without it every destination,
        including domestic ones, exits through the provider.
        """
        table_id = self._app_cfg.table_id
        if not force and self._routing_route_count(table_id) >= self.BATCH_ROUTE_MIN:
            return
        if not ctx.gateway or not ctx.interface:
            logger.warning(
                "Bypass route batch not reloaded: topology unknown "
                "(gateway=%r interface=%r)",
                ctx.gateway,
                ctx.interface,
            )
            return
        ru_cache_path = self._paths.get("ru_subnets", "cache/ru-subnets.txt")
        routes = self._bypass_loader.load_all(
            ru_cache_path=ru_cache_path,
            bypass_domains=self._bypass_cfg.domains,
            bypass_subnets=self._bypass_cfg.subnets,
            vpn_domains=self._vpn_routes_cfg.domains,
            vpn_wildcards=self._vpn_routes_cfg.wildcards,
            vpn_subnets=self._vpn_routes_cfg.subnets,
            gateway=ctx.gateway,
            interface=ctx.interface,
            table_id=table_id,
        )
        self._route_table.load_batch(routes, table_id)
        logger.info("Bypass route batch loaded: %d entries", len(routes))

    # ── Liveness verification and the recovery ladder ─────────────────────

    VERIFY_TARGETS = ("https://www.google.com", "https://www.cloudflare.com")

    async def verify_tunnel(self, timeout: int = 8) -> bool:
        """Return True only when traffic really flows through sing-box.

        The device state is the cheapest discriminator, and the probe runs
        through the SOCKS inbound so a tun0 that silently lost its carrier
        cannot be mistaken for a working tunnel (the kernel would otherwise
        fall back to the physical uplink and a plain curl would still succeed).

        Args:
            timeout: Per-probe curl timeout in seconds.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._verify_tunnel_sync, timeout)

    def _verify_tunnel_sync(self, timeout: int) -> bool:
        link = self._shell.run("ip -br link show tun0 2>/dev/null", capture=True)
        fields = (link.stdout or "").split() if link is not None else []
        if len(fields) < 2 or fields[1] != "UP":
            logger.warning(
                "Tunnel verification: tun0 is not UP (%r)",
                (link.stdout or "").strip() if link is not None else "",
            )
            return False
        if not self._rules.has_catchall(self._app_cfg.table_id):
            logger.warning(
                "Tunnel verification: no rule routes traffic into table %s — the "
                "SOCKS inbound answers but the host exits through the physical "
                "uplink",
                self._app_cfg.table_id,
            )
            return False
        host = self._tunnel_cfg.socks5_host
        port = self._tunnel_cfg.socks5_port
        for url in self.VERIFY_TARGETS:
            result = self._shell.run(
                "curl -s -o /dev/null -w '%%{http_code}' --max-time %d "
                "--socks5-hostname %s:%d %s"
                % (timeout, host, port, url),
                capture=True,
                timeout=timeout + 2,
            )
            code = (result.stdout or "").strip() if result is not None else ""
            if (
                result is not None
                and result.returncode == 0
                and code.isdigit()
                and code != "000"
            ):
                logger.info("Tunnel verification OK: %s -> HTTP %s", url, code)
                return True
        logger.warning(
            "Tunnel verification failed: no probe through SOCKS %s:%d", host, port
        )
        return False

    async def restart_and_verify(self, ctx: RuntimeContext) -> bool:
        """Restart both tunnel processes with the current config, then verify."""
        await self.restart_tunnel(ctx)
        return await self.verify_tunnel()

    async def teardown_network(self) -> None:
        """Emergency teardown — remove ALL VPN networking modifications.

        Called on: FAILED state entry, SIGTERM/SIGINT, and `vpn stop` IPC.
        Idempotent: safe to call multiple times, even if partially cleaned.
        """
        logger.info("=== VPN Network Teardown ===")
        table_id = self._app_cfg.table_id

        # 1. Kill processes (best-effort — may already be dead)
        self._shell.run("pkill sing-box 2>/dev/null || true")
        self._shell.run("pkill tun2socks 2>/dev/null || true")

        # 2. Tear down tun0 before flushing routes (avoids dead-device errors)
        self._tun.destroy()

        # 3. Flush table before removing rules (avoids stale lookups)
        self._route_table.flush(table_id)

        # 4. Remove ALL ip rules (while-loop for each priority — handles duplicates)
        self._rules.clear_all()

        # 5. Firewall cleanup
        self._nat.remove()
        self._mss.remove()
        self._sysctl_mgr.restore_ipv6()

        logger.info("Teardown complete — host network restored")


    def start_singbox(self, ctx: RuntimeContext) -> None:
        """Launch sing-box and place it under supervision.

        Args:
            ctx: Runtime context that receives the new process handle.
        """
        ctx.singbox = self._subprocess.popen([
            "sing-box", "run",
            "-c", "/etc/sing-box/config.json",
            "-D", "/var/lib/sing-box",
        ])
        self._watcher.watch(EventType.SINGBOX_DIED, ctx.singbox)

    def start_tun2socks(self, ctx: RuntimeContext) -> None:
        """Launch tun2socks against the sing-box SOCKS listener.

        Args:
            ctx: Runtime context that receives the new process handle.
        """
        proxy_url = "socks5://%s:%d" % (
            self._tunnel_cfg.socks5_host,
            self._tunnel_cfg.socks5_port,
        )
        ctx.tun2socks = self._tun2socks.start(proxy_url)
        self._watcher.watch(EventType.TUNNEL_DIED, ctx.tun2socks)

    async def restart_tunnel(self, ctx: RuntimeContext) -> None:
        """Replace both tunnel processes without touching host routing.

        Bootstrap, server switches and recovery all need the same thing: a
        fresh sing-box that actually listens, and a fresh tun2socks bound to
        it. Policy routing, firewall state and the tun device are reused, so
        the host is never re-routed and never left pointing at a dead tunnel.

        Args:
            ctx: Runtime context holding the process handles.

        Raises:
            VpnConnectionError: If sing-box never opens its SOCKS listener.
        """
        async with self._tunnel_lock:
            logger.info("=== Tunnel Restart ===")
            self._watcher.unwatch(EventType.SINGBOX_DIED)
            self._watcher.unwatch(EventType.TUNNEL_DIED)
            # tun2socks first: nothing may keep dialing a half-dead tunnel.
            self._shell.run("pkill tun2socks 2>/dev/null || true")
            self._shell.run("pkill sing-box 2>/dev/null || true")
            # Destroy the device instead of reusing it: a tun that outlived its
            # tun2socks keeps the table-100 default route marked "linkdown", and
            # traffic then dies inside a tunnel nobody reads.
            self._tun.destroy()
            await asyncio.sleep(0)  # let the kills land before respawning

            self.start_singbox(ctx)
            await self._wait_for_socks_port()
            self._tun.create()
            # Re-assert the default route: deleting tun0 drops it from table 100.
            self._route_table.set_default(self._app_cfg.table_id)
            self.start_tun2socks(ctx)
            # Re-assert policy routing: the rule set is kernel state that a
            # netplan apply or a DHCP lease renewal silently wipes, and a
            # restart is the moment the host is expected to be whole again.
            self.ensure_routing(ctx)
            ctx.startup_time = time.time()
            logger.info("Tunnel restart complete")

    async def _wait_for_socks_port(self, timeout: int = 15) -> None:
        """Block until sing-box accepts connections on the SOCKS port.

        Args:
            timeout: Maximum seconds to wait for the listener.

        Raises:
            VpnConnectionError: If the listener never appears.
        """
        host = self._tunnel_cfg.socks5_host
        port = self._tunnel_cfg.socks5_port
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            probe = self._shell.run("ss -ltnH 'sport = :%d' 2>/dev/null" % port, capture=True)
            if probe is not None and (probe.stdout or "").strip():
                logger.info("SOCKS listener up on %s:%d", host, port)
                return
            await asyncio.sleep(0.5)
        raise VpnConnectionError("SOCKS port %d did not open within %ds" % (port, timeout))
