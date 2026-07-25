# Phase 8 — CLI Fix & Full Functionality Verification

## Context

Container runs (HEALTHY, 7-step bootstrap), but CLI fails: `vpn-internal: executable file not found in $PATH`. Root cause: no `pip install .` in Dockerfile. Fix: restore `pip install --no-build-isolation --no-deps .`. Also: CLI commands are stubs — replace with JSON-RPC over Unix socket. After fix: 20-point functional audit through MCP SSH.

## Approach

### Step 0 — Pre-check: Container HEALTHY

```bash
ssh asus 'docker ps | grep vpn && docker logs vpn --tail 5 | grep HEALTHY'
```

### Step 1 — Fix Dockerfile

Replace manual `pip install click pyyaml python-dotenv` + add `pip install .`:

```dockerfile
# Python deps
RUN pip3 install --no-cache-dir click pyyaml python-dotenv

# ... (sing-box, tun2socks, .srs) ...

# Application — installs vpn-internal entry point via pyproject.toml
COPY pyproject.toml README.md .
COPY src/ src/
COPY config/ config/
COPY data/ data/
RUN pip3 install --no-build-isolation --no-deps --no-cache-dir .
```

Remove `ENV PYTHONPATH=/app/src` — no longer needed (pip install handles imports).
Remove `-e PYTHONPATH=/app/src` from `docker run` command in Step 4.

### Step 2 — JSON-RPC Server in State Machine

Add to `src/vpn/core/state_machine/machine.py`:

```python
import asyncio, json, os

IPC_SOCK = "/var/run/vpn.sock"

async def _start_ipc(self) -> None:
    """Start Unix socket JSON-RPC server for CLI communication."""
    if os.path.exists(IPC_SOCK):
        os.unlink(IPC_SOCK)
    self._ipc_server = await asyncio.start_unix_server(
        self._handle_rpc, path=IPC_SOCK
    )

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
        return [s.__dict__ for s in self._provider.list_servers()]
    if method == "server.current":
        return self._ctx.active_server
    if method == "server.change":
        result = self._switcher.switch(params["name"])
        # Re-apply server IP bypass rules (anti-loop — new server = new IPs)
        server_ips = self._resolver.resolve_all(
            self._paths.get("profile_keys", ""), self._shell
        )
        self._rules.clear_server_bypasses()
        for ip in server_ips:
            self._rules.add_server_bypass(ip)
        return result
    if method == "status":
        return {
            "gateway": self._ctx.gateway,
            "interface": self._ctx.interface,
            "tun2socks_alive": self._ctx.tun2socks is not None,
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
        await self._queue.put(VpnEvent(EventType.RESTART_REQUESTED))
        return {"status": "restarting"}
    raise ValueError("Unknown method: %s" % method)
```

Call `_start_ipc()` in `run()`.

### Step 3 — JSON-RPC Client in CLI

Create `src/vpn/cli/ipc.py`:

```python
import json, socket

SOCK = "/var/run/vpn.sock"

def call(method: str, params: dict | None = None) -> dict | list | str:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(SOCK)
    sock.sendall(json.dumps({
        "jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1
    }).encode())
    sock.shutdown(socket.SHUT_WR)
    data = sock.recv(65536)
    sock.close()
    resp = json.loads(data)
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp["result"]
```

Rewrite `cli/main.py` Click commands to call `ipc.call()`.

### Step 4 — Rebuild & Redeploy

```bash
DOCKER_BUILDKIT=0 docker build -t vpn:latest .
docker tag vpn:latest 192.168.0.131:5000/vpn:latest && docker push 192.168.0.131:5000/vpn:latest
ssh asus 'docker pull localhost:5000/vpn:latest && docker stop vpn 2>/dev/null; docker rm vpn 2>/dev/null'
ssh asus 'docker run -d --name vpn --net=host --cap-add=NET_ADMIN --device /dev/net/tun:/dev/net/tun --restart=unless-stopped localhost:5000/vpn:latest'
```

### Step 5 — 20-Point Functional Audit via MCP SSH

| # | Command | Expected |
|---|---|---|
| 0 | `which vpn` | `/usr/local/bin/vpn` |
| 1 | `vpn --help` | Click help with server/status/bypass/restart |
| 2 | `vpn server list` | 11 servers: name, country, IP, port |
| 3 | `vpn server current` | Active server name |
| 4 | `vpn server change --name barguzin` | Switches server, confirms |
| 5 | `vpn status` | Gateway, tun0 state, uptime |
| 6 | `vpn restart` | Forces RESTARTING (check logs for state transition) |
| 7 | `vpn bypass list` | Current bypass domains |
| 8 | `vpn bypass add --domain example.com && ip route show table 100 \| grep example.com` | Domain added AND route present |
| 9 | `vpn bypass remove --domain example.com` | Domain removed |
| 10 | `ip addr show tun0` | tun0 UP, 198.18.0.1/15 |
| 11 | `ss -tlnp \| grep 3066` | SOCKS5 listening |
| 12 | `curl -sI --socks5-hostname 127.0.0.1:3066 https://google.com` | HTTP 200+ |
| 13 | `docker exec vpn sing-box check -c /etc/sing-box/config.json` | Config valid |
| 14 | `docker exec vpn python3 -c "from vpn.config import get_servers_config; print(len(get_servers_config().servers))"` | 11 |
| 15 | `docker exec vpn cat /etc/sing-box/config.json \| python3 -m json.tool \| head -5` | Valid JSON |
| 16 | `grep vpn /var/log/syslog \| tail -20` | Logs present, no FATAL |
| 17 | `ip rule show \| head -15` | Priority rules 1-30 present |
| 18 | `ip route show table 100 \| wc -l` | > 8500 routes |
| 19 | Telegram notification after `vpn restart` | Alert received |
| — | `vpn emergency-reset` | SKIP on live Asus |

## Verification

All 19 automated checks + 1 manual (Telegram) pass.

## Critical Files

- `Dockerfile` — restore `pip install --no-build-isolation --no-deps .`
- `src/vpn/core/state_machine/machine.py` — add `_start_ipc()`, `_handle_rpc()`, `_dispatch()`
- `src/vpn/cli/ipc.py` — new file: JSON-RPC client over Unix socket
- `src/vpn/cli/main.py` — rewrite Click commands to use `ipc.call()`
