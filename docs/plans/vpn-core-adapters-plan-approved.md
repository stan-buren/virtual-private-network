# VPN Orchestrator — Core & Adapters Architecture

## Context

Greenfield rewrite of the VPN orchestration stack. The old `vpn_daemon.py` (934 lines: hardcoded paths, secrets in source, `time.sleep` polling, mixed concerns) is discarded entirely. New system: hexagonal architecture (Ports & Adapters), event-driven asyncio state machine, Docker-packaged with sing-box baked in, full CLI on the Asus host, syslog observability over TCP to the development machine.

## Architecture Overview

### Hexagonal Pattern — Provider-Agnostic Core

The core (`src/vpn/core/`) defines **Ports** (Protocol interfaces) as its only contact with the outside world. Adapters (`src/vpn/adapters/akonit/`) implement these ports. The core knows nothing about "Akonit", "Vanya", or any specific VPN provider. Switching providers means writing a new adapter — zero changes to core.

```
                    ┌──────────────────────────┐
                    │       CORE (ports.py)     │
                    │   VpnProviderPort         │◄── Adapter: akonit/provider.py
                    │   ShellPort               │◄── Adapter: system/shell.py
                    │   FilesystemPort          │◄── Adapter: system/filesystem.py
                    │   SubprocessPort          │◄── Adapter: system/subprocess.py
                    │   HttpPort                │◄── Adapter: http/urllib_http.py
                    └──────────────────────────┘
```

### Event-Driven State Machine — No Polling

The daemon is a finite state machine driven by an `asyncio.Queue` of events. Components (process watchers, health checker, CLI handler, OS signal handler) **push** events into the queue. The state machine **pulls** and reacts. No `while True: sleep; check; if fail: ...` — that pattern is banned.

```
                    ┌─────────────┐
    SIGTERM ───────→│             │
    TUNNEL_DIED ──→│  asyncio    │──→ State Machine
    HEALTH_FAIL ──→│  .Queue     │     │
    CLI_CMD     ──→│             │     ▼
                    └─────────────┘  BOOTSTRAPPING → HEALTHY → DEGRADED
                                                              │
                                         RESTARTING ←─────────┘
                                              │
                                          FAILED → sys.exit(1)
```

States and transitions:

| State | On enter | Exits to | Trigger |
|---|---|---|---|
| `BOOTSTRAPPING` | Deploy config, discover topology, configure routing/firewall, start sing-box, start tun2socks | `HEALTHY` | `BOOTSTRAP_DONE` |
| `HEALTHY` | Start health checker timer (randomized 25-55s interval) | `DEGRADED` | `HEALTH_FAIL` |
| `DEGRADED` | Log warning, notify Telegram on 2nd consecutive fail | `HEALTHY` | `HEALTH_OK` |
| `DEGRADED` | — | `RESTARTING` | `HEALTH_FAIL` (3rd consecutive) |
| `RESTARTING` | Restart sing-box, wait 2s for port, restart tun2socks. Timeout: 10s — if port not up → `FAILED` | `HEALTHY` | `BOOTSTRAP_DONE` |
| `RESTARTING` | — | `FAILED` | `RESTART_TIMEOUT` or `TUNNEL_DIED` repeatedly |
| `FAILED` | Send final Telegram alert with `last_error`. `sys.exit(1)` | (container restart) | — |

Per-state timeouts prevent hangs: if `BOOTSTRAPPING` waits >60s for `BOOTSTRAP_DONE`, it emits `TIMEOUT` and transitions to `FAILED`. Process watchers use `await process.wait()` (not `poll()` in a loop), so the OS wakes the event loop only when the process actually exits — zero CPU overhead.

### CLI Architecture

CLI lives **inside** the Docker container. On the Asus host, a 5-line shell wrapper proxies commands:

```bash
#!/bin/bash
# /usr/local/bin/vpn — installed ONCE on first deploy
exec docker exec -i vpn vpn-internal "$@"
```

User types `vpn server change --barguzin` on the Asus terminal → `docker exec` → container's Click CLI → JSON-RPC over Unix socket (`/var/run/vpn.sock` inside container) → daemon responds.

Commands:

| Command | Behavior |
|---|---|
| `vpn server list` | Table: name, country, IP, port, status |
| `vpn server current` | Active server name |
| `vpn server change --name barguzin` | Switch to specified server |
| `vpn status` | Gateway, tun0 state, active server, uptime |
| `vpn logs` | Tail recent logs (from syslog) |
| `vpn bypass add --domain example.com` | Add to `config/bypass.yaml`, re-apply routes |
| `vpn bypass remove --domain example.com` | Remove from `config/bypass.yaml`, re-apply routes |
| `vpn bypass list` | Show current bypass list |
| `vpn restart` | Force RESTARTING state transition |
| `vpn emergency-reset` | Wipe all rules, routes, tun0 — clean network slate |

### Provider Port — Switching VPN Providers

`VpnProviderPort` (defined in `src/vpn/core/ports.py`) is the contract every provider adapter fulfills:

```python
class VpnProviderPort(Protocol):
    def list_servers(self) -> list[ServerInfo]: ...
    def get_server(self, name: str) -> ServerInfo: ...
    def build_singbox_config(self, server_name: str) -> str: ...
    def sanitize_config(self, raw: dict) -> dict: ...
```

The Akonit adapter (`src/vpn/adapters/akonit/provider.py`) implements this using:
- `data/profile_keys_akonit_24_07_2026.json` — 11 VLESS Reality outbounds
- `config/servers.yaml` — maps CLI names (`barguzin`) to JSON outbound tags (`🇷🇺 Баргузин - Россия 🔗`)

To add a new provider: create `adapters/vanya/provider.py` implementing `VpnProviderPort`. Change `provider: vanya` in `config/app.yaml`. Core untouched.

### Deploy Pipeline

Local Docker Registry on Asus (standard production pattern):

```
Dev machine (.93)                Asus (.131)
┌──────────────┐                ┌─────────────────────┐
│ docker build │   push         │ localhost:5000       │
│ docker push  │──────────────→│ Docker Registry      │
└──────────────┘   (cable)     │ docker pull          │
                               │ docker stop old      │
                               │ docker run new       │
                               │ docker image prune -f│
                               └─────────────────────┘
```

Deploy script (`just deploy`):
```bash
TAG=$(date +%Y%m%d-%H%M%S)
docker build -t vpn:$TAG -t vpn:latest .
docker tag vpn:$TAG asus:5000/vpn:$TAG
docker push asus:5000/vpn:$TAG
ssh asus "
  docker pull localhost:5000/vpn:$TAG
  docker stop vpn 2>/dev/null || true
  docker rm vpn 2>/dev/null || true
  docker run -d --name vpn
    --net=host --cap-add=NET_ADMIN
    --restart=unless-stopped
    --log-driver=syslog
    --log-opt syslog-address=tcp://192.168.0.93:514
    --log-opt syslog-facility=local0
    --log-opt tag=vpn
    localhost:5000/vpn:$TAG
  # Healthcheck: ensure CLI responds before declaring success
  for i in \$(seq 1 10); do
    docker exec vpn vpn-internal status 2>/dev/null && break
    sleep 2
  done
  docker image prune -a -f --filter 'until=24h'
"
```

First deploy also: (a) start Registry on Asus, (b) create `/usr/local/bin/vpn` wrapper, (c) stop old `sing-box hiddify-core vpn-hiddify` services.

### Observability — syslog over TCP

Logging driver: `syslog` → TCP → `192.168.0.93:514` → `rsyslog` → `/mnt/home_server/storage/logs/vpn.log`.

Logger configuration (`src/vpn/logger/logger_config.py`):
- Scoped to `"vpn"` — never root logger
- `logger.propagate = False` — isolates from third-party noise
- NO f-strings in log calls — `%s` / `%d` placeholders for deferred evaluation and template grouping
- `logger.exception()` for caught exceptions (auto-attaches traceback)
- Custom exception hierarchy: `VpnError` → `VpnConfigError`, `VpnConnectionError`, `VpnTunnelError`, `VpnHealthError`
- DEBUG level emits full context: state transitions, event queue snapshots, shell command output, config diffs

### Notification — Telegram

Event-text config in `config/notifications.yaml`:
```yaml
events:
  daemon_started: "🟢 VPN daemon started. Server: {server}, Gateway: {gateway}"
  server_changed: "🔄 Switched {old} → {new} ({country})"
  health_degraded: "⚠️ Health check failed {streak}/3. Last target: {target}"
  recovery_started: "🔧 Restarting sing-box + tun2socks (attempt #{count})"
  recovery_ok: "✅ Recovery successful. Uptime: {uptime}s"
  recovery_failed: "💀 FAILED after {count} attempts.\nLast error: {error}\nContainer restarting..."
  tunnel_died: "🔥 tun2socks process died. Restarting..."
  shutdown: "🛑 Graceful shutdown."
```

Secrets (`VPN_TELEGRAM_TOKEN`, `VPN_TELEGRAM_CHAT_ID`) in `.env`, NEVER in YAML.

## Directory Structure

```
/home/donald_trump/developer/vpn/
├── .github/
├── .env.example
├── pyproject.toml
├── justfile
├── Dockerfile
├── tests/
├── config/
│   ├── paths.yaml               # All filesystem paths, relative to PROJECT_ROOT
│   ├── app.yaml                 # tag, table_id, chain_name, provider, services
│   ├── network.yaml             # tun0 IP/MTU, DNS servers, LAN subnets, MSS value
│   ├── health.yaml              # health check targets, user-agents, intervals, thresholds
│   ├── tunnel.yaml              # SOCKS5 proxy host/port, MacBook proxy settings
│   ├── notification.yaml        # event templates, retry count, timeout
│   ├── servers.yaml             # CLI name → JSON outbound tag mapping (11 servers)
│   ├── bypass.yaml              # domains + subnets to bypass VPN (was custom-bypass.txt)
│   └── vpn-routes.yaml          # domains + wildcards + subnets forced through VPN (was custom-vpn.txt)
├── data/
│   └── profile_keys_akonit_24_07_2026.json   # VLESS Reality profile (11 outbounds)
├── docs/
│   └── plans/
│       └── migrate-to-new-architecture-plan.md
└── src/
    └── vpn/
        ├── __init__.py
        ├── __main__.py              # Entry point: wire adapters → state machine → asyncio.run()
        ├── config/
        │   ├── __init__.py
        │   ├── paths.py             # PROJECT_ROOT discovery, load_paths_config(), dynamic __getattr__
        │   ├── config_loader.py     # @cache facade: get_app_config(), get_network_config(), ...
        │   └── core/
        │       ├── __init__.py
        │       ├── app.py           # AppConfig (frozen dataclass, _from_yaml())
        │       ├── network.py       # NetworkConfig
        │       ├── health.py        # HealthConfig
        │       ├── tunnel.py        # TunnelConfig
        │       ├── notification.py  # NotificationConfig
        │       ├── servers.py       # ServersConfig (CLI name → tag → outbound)
        │       ├── bypass.py        # BypassConfig (from bypass.yaml)
        │       └── vpn_routes.py    # VpnRoutesConfig (from vpn-routes.yaml)
        ├── logger/
        │   ├── __init__.py          # Re-exports: VpnError hierarchy, setup_logging
        │   ├── exceptions.py        # VpnError → VpnConfigError, VpnConnectionError, VpnTunnelError, VpnHealthError
        │   ├── logger_config.py     # setup_logging(level, use_json) — scoped "vpn", propagate=False
        │   └── core/
        │       ├── __init__.py
        │       └── json_formatter.py # Structured JSON formatter for syslog
        ├── core/
        │   ├── __init__.py
        │   ├── ports.py             # ALL Protocol definitions: VpnProviderPort, ShellPort, FilesystemPort, SubprocessPort, HttpPort
        │   ├── events.py            # VpnEvent enum + dataclass payloads
        │   ├── state_machine/
        │   │   ├── __init__.py
        │   │   ├── machine.py       # VpnStateMachine: event queue loop, transition_to()
        │   │   ├── context.py       # RuntimeContext dataclass (mutable state: gateway, interface, fail_streak, recovery_count, last_error, active_server)
        │   │   └── states/
        │   │       ├── __init__.py
        │   │       ├── base.py      # VpnState ABC: on_enter(), on_exit(), handle(event)
        │   │       ├── bootstrapping.py
        │   │       ├── healthy.py
        │   │       ├── degraded.py
        │   │       ├── restarting.py
        │   │       └── failed.py
        │   ├── topology/
        │   │   ├── __init__.py
        │   │   ├── discovery.py     # TopologyDiscovery: ip route → Topology(gateway, interface)
        │   │   └── resolver.py      # ServerIpResolver, DnsResolver
        │   ├── routing/
        │   │   ├── __init__.py
        │   │   ├── tun_interface.py # TunInterface: create/destroy tun0
        │   │   ├── rule_manager.py  # RuleManager: ip rule priority constants (PRIO_SERVER_IPS=1 ... PRIO_CATCHALL=30)
        │   │   ├── route_table.py   # RouteTable: batch route injection, default gateway
        │   │   └── bypass_loader.py # BypassLoader: reads RU cache + bypass.yaml + vpn-routes.yaml → RouteEntry list
        │   ├── firewall/
        │   │   ├── __init__.py
        │   │   ├── nat.py           # NatManager: POSTROUTING chain, MASQUERADE rules
        │   │   ├── mss.py           # MssClamp: TCPMSS 1360 in mangle FORWARD
        │   │   └── sysctl.py        # SysctlManager: ip_forward, IPv6 disable/enable
        │   ├── tunnel/
        │   │   ├── __init__.py
        │   │   ├── tun2socks.py     # Tun2SocksManager: start/stop/monitor tun2socks process
        │   │   └── ssh_proxy.py     # SshTunnel: MacBook SSH SOCKS5 proxy (optional)
        │   ├── health/
        │   │   ├── __init__.py
        │   │   └── checker.py       # HealthChecker: asyncio-based curl with randomized interval
        │   ├── notification/
        │   │   ├── __init__.py
        │   │   └── telegram.py      # TelegramNotifier: IPv4-forced HTTP POST with retry
        │   ├── server_manager/
        │   │   ├── __init__.py
        │   │   ├── switcher.py      # ServerSwitcher: switch server via VpnProviderPort
        │   │   └── deployer.py      # ConfigDeployer: copy profile → sanitize → write config.json
        │   └── ru_updater/
        │       ├── __init__.py
        │       └── updater.py       # RuSubnetUpdater: asyncio background task, fetch every 24h
        ├── cli/
        │   ├── __init__.py
        │   ├── main.py              # Click group: vpn
        │   ├── server.py            # vpn server {list,current,change}
        │   ├── status.py            # vpn status
        │   ├── logs.py              # vpn logs
        │   └── bypass.py            # vpn bypass {add,remove,list}
        └── adapters/
            ├── __init__.py
            ├── system/
            │   ├── __init__.py
            │   ├── shell.py         # ShellPort: subprocess.run with timeout + logging
            │   ├── filesystem.py    # FilesystemPort: open/json/os.path/shutil wrappers
            │   └── subprocess.py    # SubprocessPort: asyncio.create_subprocess_exec wrapper
            ├── http/
            │   ├── __init__.py
            │   └── urllib_http.py   # HttpPort: urllib.request.urlopen wrapper
            └── akonit/
                ├── __init__.py
                └── provider.py      # Implements VpnProviderPort for Akonit VLESS Reality
```

## Critical Implementation Details

### Process Watchers — True Event-Driven, Not Polling

```python
# core/tunnel/tun2socks.py — CORRECT: OS wakes us when process exits
async def watch(process: asyncio.subprocess.Process, queue: asyncio.Queue):
    await process.wait()           # Blocks on OS signal, ZERO CPU
    queue.put_nowait(Event(TUNNEL_DIED, pid=process.pid))
```

Never use `process.poll()` in a `while` loop with `asyncio.sleep(1)`. That is polling disguised as asyncio.

### Per-State Timeouts — Prevent Silent Hangs

Every state sets an `asyncio.Task` timeout on `on_enter()`:

```python
# core/state_machine/states/bootstrapping.py
async def on_enter(self):
    self._timeout = asyncio.create_task(self._on_timeout())

async def _on_timeout(self):
    await asyncio.sleep(60)
    await self.machine.post(Event(TIMEOUT, state="BOOTSTRAPPING"))

async def on_exit(self):
    self._timeout.cancel()  # Clean up if we left normally
```

Without this, a state that waits for an event that never comes (e.g., sing-box started but port never opened) freezes the state machine permanently.

### Logging — Every Decision Observable

```python
# GOOD: deferred evaluation, template-preserving
logger.debug("Rule added: priority=%d, subnet=%s, target=table main", prio, subnet)

# BAD: f-string evaluated even if DEBUG disabled
logger.debug(f"Rule added: priority={prio}, subnet={subnet}, target=table main")
```

Log at state transitions: `on_enter` and `on_exit` of every state. Log at event post and event handle. Log every shell command with its exit code and stderr. At DEBUG level, the log is a complete forensic trace.

### Priority Schema — Load-Bearing Constants

```python
# core/routing/rule_manager.py
PRIO_SERVER_IPS  = 1    # VLESS server IPs → table main (anti-loop)
PRIO_DNS_START   = 3    # DNS 3-6 → table main (MUST be < WireGuard's 8-9)
PRIO_DNS_END     = 6
PRIO_LAN_START   = 10   # LAN subnets 10-12 → table main
PRIO_LAN_END     = 12
PRIO_TORRENT     = 20   # fwmark 1 → table main (MAM torrent)
PRIO_CATCHALL    = 30   # table 100 → tun0 (VPN catch-all)
```

These numbers are NOT configurable. Changing them breaks WireGuard coexistence or leaks traffic. They are module-level constants with docstring explanations.

## Verification

1. **Config loading**: `cd /home/donald_trump/developer/vpn && uv run python -c "from vpn.config.config_loader import get_servers_config; print(get_servers_config().servers['barguzin'])"` — prints server info for Баргузин.

2. **Server list CLI**: `docker exec vpn vpn-internal server list` — prints 11 servers with country, IP, port.

3. **Dry-run bootstrap**: Mock all adapters. Run `VpnStateMachine` with initial `BOOTSTRAP_DONE` event. Verify transition: BOOTSTRAPPING → HEALTHY. Verify `on_enter(HEALTHY)` starts `HealthChecker` asyncio task.

4. **Failure simulation in dry-run**: Post 3× `HEALTH_FAIL` events. Verify: HEALTHY → DEGRADED → DEGRADED → RESTARTING. Verify Telegram notification sent on 2nd fail.

5. **Docker build**: `docker build -t vpn:latest .` succeeds. `docker run --rm vpn:latest vpn-internal --help` prints help text.

6. **Remote deploy**: `just deploy`. After deploy: `ssh asus vpn status` prints active server, gateway, tunnel state. `ssh asus vpn server change --name sirokko` switches to German server.

## Assumptions & Contingencies

- **Docker 29.3.1 is installed on Asus** (user confirmed). Registry on port 5000 must not conflict with existing services.
- **sing-box binary is baked into Docker image** (installed via `apt` or downloaded release binary in Dockerfile). The host's old sing-box is stopped before first deploy — this is an explicit step in the `just deploy` script.
- **`docker exec` wrapper requires root or `docker` group.** Asus daemon runs as root (needs `NET_ADMIN`), so this is satisfied.
- **Profile keys JSON format** is stable. Server tags in `config/servers.yaml` use substring matching against JSON `"tag"` fields. If Akonit changes tag format, update `servers.yaml` — no core changes needed.
- **Secrets in `.env`** loaded via `python-dotenv` at startup. `.env` is gitignored. `.env.example` committed with placeholder values.
- **Custom bypass/vpn lists converted to YAML** once. Old `.txt` files remain in repo root for reference, NOT used by new system.
- **RU subnet cache** is fetched by a background asyncio task inside the container on startup and every 24h thereafter. No systemd timer, no cron.
- **Old scripts** (`vless_updater.py`, `gemini_check_vpn.py`, `dadya_vanya.py`, old `vpn_daemon.py`) are NOT ported. They remain in repo root for reference only.
