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
        paths: dict[str, str] | None = None,
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
        if method == "restart":
            await self.post(VpnEvent(EventType.RESTART_REQUESTED))
            return {"status": "restarting"}
        raise ValueError("Unknown method: %s" % method)
