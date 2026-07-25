"""Event-driven state machine engine for the VPN daemon.

The state machine consumes events from an asyncio.Queue and delegates to the
current state's handle() method. Also serves JSON-RPC over Unix socket for CLI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Type

from vpn.core.events import EventType, VpnEvent
from vpn.core.state_machine.context import RuntimeContext
from vpn.core.state_machine.states.base import VpnState

logger = logging.getLogger("vpn")
IPC_SOCK = "/var/run/vpn.sock"


class VpnStateMachine:
    """Event-driven finite state machine for VPN lifecycle management."""

    def __init__(
        self,
        initial_state_cls: Type[VpnState],
        *,
        provider: Any = None,
        switcher: Any = None,
        resolver: Any = None,
        rules: Any = None,
        shell: Any = None,
        bypass_cfg: Any = None,
        vpn_routes_cfg: Any = None,
        dns_resolver: Any = None,
        paths: dict[str, str] | None = None,
        notifier: Any = None,
    ) -> None:
        self.context = RuntimeContext()
        self._event_queue: asyncio.Queue[VpnEvent] = asyncio.Queue()
        self._current_state: VpnState | None = None
        self._initial_state_cls = initial_state_cls
        self._running = False
        self._provider = provider
        self._switcher = switcher
        self._resolver = resolver
        self._rules = rules
        self._shell = shell
        self._bypass_cfg = bypass_cfg
        self._vpn_routes_cfg = vpn_routes_cfg
        self._dns_resolver = dns_resolver
        self._notifier = notifier
        self._paths = paths or {}
        self._ipc_server: asyncio.AbstractServer | None = None

    @property
    def current_state(self) -> VpnState | None:
        return self._current_state

    async def post(self, event: VpnEvent) -> None:
        await self._event_queue.put(event)
        logger.debug("Event posted: %s", event.type.name)

    async def transition_to(self, state_cls: Type[VpnState]) -> None:
        if self._current_state:
            await self._current_state.on_exit()
            logger.debug("Exited state: %s", type(self._current_state).__name__)
        self._current_state = state_cls(self)
        logger.info("Transitioned to: %s", state_cls.__name__)
        await self._current_state.on_enter()

    async def run(self) -> None:
        self._running = True
        await self.transition_to(self._initial_state_cls)
        await self._start_ipc()
        logger.info("State machine running")
        while self._running:
            try:
                event = await self._event_queue.get()
                logger.debug("Processing event: %s", event.type.name)
                if self._current_state:
                    await self._current_state.handle(event)
            except asyncio.CancelledError:
                logger.info("State machine cancelled")
                break
            except Exception:
                logger.exception("Unhandled error in state machine loop")

    def stop(self) -> None:
        self._running = False

    # ── IPC ───────────────────────────────────────────────────────────────

    async def _start_ipc(self) -> None:
        if os.path.exists(IPC_SOCK):
            os.unlink(IPC_SOCK)
        self._ipc_server = await asyncio.start_unix_server(
            self._handle_rpc, path=IPC_SOCK
        )
        logger.info("IPC server listening on %s", IPC_SOCK)

    async def _handle_rpc(self, reader, writer) -> None:
        raw = await reader.read()
        req = json.loads(raw)
        method = req.get("method", "")
        params = req.get("params", {})
        try:
            result = await self._dispatch(method, params)
            resp = {"jsonrpc": "2.0", "result": result, "id": req.get("id")}
        except Exception as e:
            resp = {"jsonrpc": "2.0", "error": str(e), "id": req.get("id")}
        writer.write(json.dumps(resp).encode())
        await writer.drain()
        writer.close()

    async def _dispatch(self, method: str, params: dict):
        if method == "server.list":
            servers = self._provider.list_servers()
            return [{"name": s.name, "tag": s.tag, "country": s.country, "host": s.host, "port": s.port} for s in servers]
        if method == "server.current":
            return {"server": self.context.active_server}
        if method == "server.change":
            result = self._switcher.switch(params["name"], restart_service=False)
            ctx = self.context
            orch = self._orchestrator
            # Kill old sing-box (guarded)
            if ctx.singbox is not None:
                ctx.singbox.kill()
            # Start new sing-box via proper subprocess
            ctx.singbox = orch._subprocess.popen([
                "sing-box", "run",
                "-c", "/etc/sing-box/config.json",
                "-D", "/var/lib/sing-box",
            ])
            # Restart tun2socks
            proxy_url = "socks5://127.0.0.1:3066"
            ctx.tun2socks = orch._tun2socks.start(proxy_url)
            # Re-apply anti-loop bypass rules
            profile_path = self._paths.get("profile_keys", "")
            server_ips = self._resolver.resolve_all(profile_path, self._shell)
            self._rules.clear_server_bypasses()
            for ip in server_ips:
                self._rules.add_server_bypass(ip)
            ctx.active_server = params["name"]
            return result
        if method == "status":
            return {
                "gateway": self.context.gateway,
                "interface": self.context.interface,
                "tun2socks_alive": self.context.tun2socks is not None,
            }
        if method == "bypass.list":
            return self._bypass_cfg.domains
        if method == "bypass.add":
            self._bypass_cfg.domains.append(params["domain"])
            return self._bypass_cfg.domains
        if method == "bypass.remove":
            self._bypass_cfg.domains.remove(params["domain"])
            return self._bypass_cfg.domains
        if method == "stop":
            ctx = self.context
            orch = self._orchestrator
            table_id = orch._app_cfg.table_id
            if ctx.singbox is not None:
                ctx.singbox.kill()
            if ctx.tun2socks is not None:
                ctx.tun2socks.kill()
            orch._tun.destroy()
            orch._route_table.flush(table_id)
            self._rules.clear_all()
            orch._nat.remove()
            orch._mss.remove()
            orch._sysctl_mgr.restore_ipv6()
            from vpn.core.state_machine.states.stopped import StoppedState
            await self.transition_to(StoppedState)
            return {"status": "stopped"}
        if method == "start":
            orch = self._orchestrator
            table_id = orch._app_cfg.table_id
            # Idempotent mini-cleanup
            self._shell.run("ip link del tun0 2>/dev/null || true")
            self._shell.run("ip route flush table %s 2>/dev/null || true" % table_id)
            self._shell.run("pkill sing-box 2>/dev/null || true")
            self._shell.run("pkill tun2socks 2>/dev/null || true")
            orch._nat.remove()
            orch._mss.remove()
            self._rules.clear_all()
            from vpn.core.state_machine.states.bootstrapping import BootstrappingState
            await self.transition_to(BootstrappingState)
            return {"status": "starting"}
        if method == "route.list":
            return {
                "domains": list(self._vpn_routes_cfg.domains),
                "wildcards": list(self._vpn_routes_cfg.wildcards),
                "subnets": list(self._vpn_routes_cfg.subnets),
            }
        if method == "route.add":
            orch = self._orchestrator
            table_id = orch._app_cfg.table_id
            if "domain" in params:
                ips = self._dns_resolver.resolve_ipv4(params["domain"], self._shell)
                for ip in ips:
                    self._shell.run("ip route add %s dev tun0 table %s 2>/dev/null || true" % (ip, table_id))
                self._vpn_routes_cfg.domains.append(params["domain"])
                self.context.route_ips[params["domain"]] = ips
                return {"domain": params["domain"], "ips": ips}
            if "wildcard" in params:
                self._vpn_routes_cfg.wildcards.append(params["wildcard"])
                return {"wildcard": params["wildcard"], "applied": False, "note": "takes effect on next restart"}
            if "subnet" in params:
                self._shell.run("ip route add %s dev tun0 table %s 2>/dev/null || true" % (params["subnet"], table_id))
                self._vpn_routes_cfg.subnets.append(params["subnet"])
                return {"subnet": params["subnet"]}
        if method == "route.remove":
            orch = self._orchestrator
            table_id = orch._app_cfg.table_id
            if "domain" in params:
                for ip in self.context.route_ips.pop(params["domain"], []):
                    self._shell.run("ip route del %s table %s 2>/dev/null || true" % (ip, table_id))
                self._vpn_routes_cfg.domains.remove(params["domain"])
                return {"domain": params["domain"]}
            if "wildcard" in params:
                self._vpn_routes_cfg.wildcards.remove(params["wildcard"])
                return {"wildcard": params["wildcard"]}
            if "subnet" in params:
                self._shell.run("ip route del %s table %s 2>/dev/null || true" % (params["subnet"], table_id))
                self._vpn_routes_cfg.subnets.remove(params["subnet"])
                return {"subnet": params["subnet"]}
        if method == "restart":
            await self.post(VpnEvent(EventType.RESTART_REQUESTED))
            return {"status": "restarting"}
        raise ValueError("Unknown method: %s" % method)
