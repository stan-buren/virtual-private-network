# VPN Orchestrator — Core & Adapters Architecture Plan

## Context

Complete greenfield rewrite of the VPN orchestration stack. The old `vpn_daemon.py` (934 lines of hardcoded spaghetti) is discarded entirely — we design fresh, preserving only the *behaviors* (tun2socks bridging, RU bypass routing, self-healing watchdog, Telegram alerts, sing-box config management). 

Target architecture: **Core & Adapters** following the entsoe-pipeline SSOT pattern (frozen dataclasses, `_from_yaml()`, `@cache` facade, `paths.py` as path authority, scoped logger, Google docstrings). Delivered as a Docker image containing sing-box + all deps, deployable on any Linux host with one command. Full CLI for runtime management (switch servers by name, view status, tail logs).

## Approach

### Phase 0 — Foundation: Project Scaffold & SSOT Layer

All config lives in `config/*.yml`. Secrets (Telegram token) in `.env`. Paths resolved through a single `paths.py` authority. Logger follows entsoe pattern in dedicated `src/vpn/logger/`.

#### 0.1 Fix existing scaffolding

- **Move** `src/core/config/core/paths.py` → `src/vpn/config/paths.py` (single `paths.py` at package level, NOT nested `core/config/core/`).
- **Populate** `config/paths.yaml` with every filesystem path the service touches, relative to `PROJECT_ROOT`:
  ```yaml
  cache_dir: cache
  ru_subnets: cache/ru-subnets.txt
  bypass_list: config/bypass.yaml
  vpn_routes_list: config/vpn-routes.yaml
  log_dir: logs
  log_file: logs/vpn.log
  profile_keys: data/profile_keys_akonit_24_07_2026.json
  sing_box_config: /etc/sing-box/config.json   # target-machine absolute path
  ```
- **Create** `config/app.yaml`:
  ```yaml
  app:
    tag: hiddify-vpn
    table_id: "100"
    chain_name: VPN_ASUS_OUTPUT
    sing_box_service: sing-box
    unbound_service: unbound
  ```
- **Convert** `custom-bypass.txt` → `config/bypass.yaml`:
  ```yaml
  bypass:
    domains: [api.deepseek.com, timeweb.cloud, stan-buren.ru, a5academy.ru, collegepss.ru]
    subnets: []
  ```
- **Convert** `custom-vpn.txt` → `config/vpn-routes.yaml`:
  ```yaml
  vpn_routes:
    domains: [api.telegram.org, speedtest.net, archive.org, knaben.xyz, rutracker.org, myanonamouse.net]
    wildcards: [audiobookbay.*]
    subnets: []
  ```

#### 0.2 Logger module (`src/vpn/logger/`)

Mirror entsoe `logger/` structure exactly:

```
src/vpn/logger/
├── __init__.py            # Re-exports: VpnError hierarchy, setup_logging, ObservabilityLogger
├── exceptions.py          # VpnError base → VpnConfigError, VpnConnectionError, VpnTunnelError, VpnHealthError
├── logger_config.py       # setup_logging(level, use_json) — scoped to "vpn", propagate=False
├── core/
│   ├── __init__.py
│   └── json_formatter.py  # Structured JSON log formatter for Docker stdout
```

**Rules (from entsoe logging guide):**
- `logger = logging.getLogger("vpn")` — scoped, never root.
- `logger.propagate = False`.
- NO f-strings in log calls — use `%s` / `%d` placeholders: `logger.info("Tunnel established on %s", interface)`.
- `logger.exception()` for caught exceptions (auto-attaches traceback).
- Custom exception hierarchy: `VpnError` → `VpnConfigError`, `VpnConnectionError`, `VpnTunnelError`, `VpnHealthError`.

#### 0.3 pyproject.toml — update with deps & CLI entry point

```toml
[project]
name = "vpn"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pyyaml", "click"]

[project.scripts]
vpn = "vpn.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

#### 0.4 VLESS server registry

The profile keys JSON (`data/profile_keys_akonit_24_07_2026.json`) contains 11 VLESS outbounds with tags like `🇷🇺 Баргузин - Россия 🔗`, `🇩🇪 Сирокко - Германия 🌊 ✂️`, etc.

**Create `config/servers.yaml`** — human-readable registry mapping CLI names to JSON outbound tags:

```yaml
servers:
  barguzin:
    tag: "🇷🇺 Баргузин - Россия 🔗"
    country: ru
  sirokko:
    tag: "🇩🇪 Сирокко - Германия 🌊 ✂️"
    country: de
  siverko:
    tag: "🇫🇮 Сиверко - Финляндия 🌊🛡"
    country: fi
  zonda:
    tag: "🇵🇱 Зонда - Польша ⚡"
    country: pl
  gregal:
    tag: "🇳🇱 Грегаль - Нидерланды 🌊"
    country: nl
  …  # all 11
```

This is the mapping the CLI `vpn change --barguzin` uses to find the right outbound in the profile JSON.

### Phase 1 — Config SSOT (`src/vpn/config/`)

Each YAML file → frozen dataclass in `config/core/<name>.py` with `_from_yaml()`. Facade `config_loader.py` re-exports cached getters.

```
src/vpn/config/
├── __init__.py
├── config_loader.py       # Facade: @cache getters for every config
├── paths.py               # PROJECT_ROOT, load_paths_config(), __getattr__
└── core/
    ├── __init__.py
    ├── app.py             # AppConfig
    ├── network.py         # NetworkConfig
    ├── health.py          # HealthConfig
    ├── tunnel.py          # TunnelConfig
    ├── notification.py    # NotificationConfig
    ├── servers.py         # ServersConfig (the registry)
    ├── bypass.py          # BypassConfig  (from bypass.yaml)
    └── vpn_routes.py      # VpnRoutesConfig (from vpn-routes.yaml)
```

**Pattern (copy entsoe `ports.py` exactly):**

```python
@dataclass(frozen=True)
class AppConfig:
    tag: str
    table_id: str
    chain_name: str
    sing_box_service: str
    unbound_service: str

    @classmethod
    def _from_yaml(cls) -> AppConfig:
        from vpn.config.paths import CONFIG_DIR
        with (CONFIG_DIR / "app.yaml").open() as f:
            data = yaml.safe_load(f)
        app = data["app"]
        return cls(
            tag=app["tag"],
            table_id=app["table_id"],
            chain_name=app["chain_name"],
            sing_box_service=app["sing_box_service"],
            unbound_service=app["unbound_service"],
        )
```

**`config_loader.py` facade:**

```python
from functools import cache

@cache
def get_app_config() -> AppConfig:
    """Returns cached AppConfig singleton."""
    return AppConfig._from_yaml()

def get_network_config() -> NetworkConfig:
    """Lightweight delegator to master config."""
    return get_config().network
```

All delegators (like `get_network_config`) go through a single `get_config()` master that loads the composed `VpnConfig` once — exactly the entsoe composed master pattern from `python_file_architecture_guide.md` §6.

### Phase 2 — Core Business Modules (src/vpn/core/)

Seven domain modules, each receiving config via constructor injection, each depending on Protocol interfaces (never concrete adapters).

#### 2.1 `core/topology/` — Network Discovery

**Files:**
- `discovery.py` — `TopologyDiscovery` class
- `resolver.py` — `ServerIpResolver`, `DnsResolver`

**TopologyDiscovery**:
- `discover(self, shell: ShellPort) -> Topology` — runs `ip -4 route show default`, retries N times from config, parses gateway + interface. Returns `Topology(gateway: str, interface: str)` named tuple.
- Raises `VpnConnectionError` after exhaustion.

**ServerIpResolver**:
- `resolve_all(self, fs: FilesystemPort, dns: DnsResolver, profile_path: str) -> set[str]` — reads profile JSON, scans outbounds for non-loopback servers, resolves hostnames to IPv4 via `DnsResolver`. Falls back to hardcoded Barguzin IP `138.16.186.64` if profile unreadable.

**DnsResolver**:
- `available(self, test_host: str = "8.8.8.8") -> bool` — TCP connect to port 53, 3s timeout.
- `resolve_ipv4(self, hostname: str) -> list[str]` — `socket.getaddrinfo(AF_INET)` → fallback `getent ahosts`. Validates hostname against domain regex. Returns deduplicated IPv4 list.

#### 2.2 `core/routing/` — Selective Routing & RU Bypass

**Files:**
- `tun_interface.py` — `TunInterface`
- `rule_manager.py` — `RuleManager`
- `route_table.py` — `RouteTable`
- `bypass_loader.py` — `BypassLoader`

**TunInterface**:
- `create(shell: ShellPort, config: NetworkConfig) -> None` — `ip tuntap add mode tun dev tun0`, `ip addr add 198.18.0.1/15`, `ip link set mtu 1360 up`.
- `destroy(shell: ShellPort) -> None` — reverse.

**RuleManager** — the priority schema, extracted as explicit constants:

```python
# Priority constants (lower = higher priority, 1-6 must be < WireGuard's 8-9)
PRIO_SERVER_IPS = 1     # VLESS server IPs → table main (anti-loop)
PRIO_TELEGRAM = 2        # api.telegram.org → table main
PRIO_DNS_START = 3       # DNS servers 3-6 → table main
PRIO_DNS_END = 6
PRIO_LAN_START = 10      # LAN subnets 10-12 → table main
PRIO_LAN_END = 12
PRIO_TORRENT = 20        # fwmark 1 → table main (MAM torrent)
PRIO_CATCHALL = 30       # table 100 catch-all → tun0
```

- `add_server_bypass(shell, ip: str) -> None` — `ip rule add to {ip} table main priority 1`
- `add_dns_bypass(shell, ip: str, prio: int) -> None`
- `add_lan_bypass(shell, subnet: str, prio: int) -> None`
- `add_catchall(shell) -> None` — `ip rule add from all table 100 priority 30`
- `clear_all(shell) -> None` — wipe priorities 1-6, 10-12, 20, 30.

**RouteTable**:
- `load_batch(shell, routes: list[RouteEntry]) -> None` — writes `/tmp/vpn_batch.txt`, runs `ip -force -batch`. Each `RouteEntry` is either `bypass` (via gateway dev interface) or `vpn` (dev tun0).
- `set_default(shell, table_id: str) -> None` — `ip route add default dev tun0 table {table_id}`.
- `flush(shell, table_id: str) -> None`.

**BypassLoader**:
- `load(shell, fs, dns: DnsResolver, bypass_config, vpn_routes_config, ru_cache_path, gateway, interface) -> list[RouteEntry]` — reads RU cache, bypass.yaml, vpn-routes.yaml. Resolves domains/wildcards to IPs. Deduplicates. Returns combined route entries. Skips DNS resolution when `dns.available()` is False (domain entries deferred).

#### 2.3 `core/firewall/` — NAT & iptables

**Files:**
- `nat.py` — `NatManager`
- `mss.py` — `MssClamp`
- `sysctl.py` — `SysctlManager`

**NatManager**:
- `apply(shell, chain: str, wan_iface: str) -> None` — create/flush chain, add MASQUERADE for tun0 + wan, hook into POSTROUTING.
- `remove(shell, chain: str) -> None`.

**MssClamp**:
- `apply(shell) -> None` — `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1360`.
- `remove(shell) -> None`.

**SysctlManager**:
- `enable_ip_forward(shell) -> None`.
- `disable_ipv6_wan(shell) -> None` — `net.ipv6.conf.all.disable_ipv6=1`, `net.ipv6.conf.lo.disable_ipv6=0` (SOCKS5 needs [::1]).
- `restore_ipv6(shell) -> None`.

#### 2.4 `core/tunnel/` — tun2socks & Proxy

**Files:**
- `tun2socks.py` — `Tun2SocksProcess`
- `proxy.py` — `ProxyUrlBuilder`, `SshTunnel`

**Tun2SocksProcess**:
- `start(shell: SubprocessPort, proxy_url: str) -> PopenHandle` — launches `tun2socks -device tun0 -proxy {proxy_url}`. Kills old process if running.
- `stop(proc) -> None`.
- `is_alive(proc) -> bool`.

**ProxyUrlBuilder**:
- `build(config: TunnelConfig, server_ips: set[str]) -> str` — if MacBook proxy enabled, returns `socks5://{mac_ip}:{mac_port}`, else `socks5://127.0.0.1:3066`. Also triggers server IP bypass rules for direct mode.

**SshTunnel** (MacBook proxy):
- `open(config) -> PopenHandle` — `ssh -D 10080 user@host -N`.
- `close(proc) -> None`.

#### 2.5 `core/health/` — Watchdog & Recovery

**Files:**
- `checker.py` — `ConnectivityChecker`
- `watchdog.py` — `Watchdog`
- `recovery.py` — `RecoveryManager`

**ConnectivityChecker**:
- `check(shell: ShellPort, config: HealthConfig) -> bool` — picks 2 random targets + random User-Agent, runs `curl -sI --max-time 8 -A '{ua}' {url}`. Returns `True` if any succeeds.

**Watchdog**:
- `run(orchestrator_deps) -> None` — the main loop. Sleeps 25-55s random. Skips checks during grace period (120s cold start, 60s recovery). Calls checker. Accumulates fail streak. Triggers recovery at threshold (3).

**RecoveryManager**:
- `recover(shell, tunnel, routing, notifier, recovery_count: int) -> None` — restart sing-box (unless MacBook mode), wait with backoff (8s + recovery_count×5s, max 28s), restart tun2socks, re-apply routing, restart unbound. Sends Telegram notification on each recovery cycle.

#### 2.6 `core/notification/` — Telegram Alerts

**Files:**
- `telegram.py` — `TelegramNotifier`

**TelegramNotifier**:
- `send(self, http: HttpPort, message: str, retries: int = 3, delay: int = 5) -> None` — constructs URL, forces IPv4 via `socket.getaddrinfo` monkey-patch (IPv6 disabled on WAN), retries with backoff. Token and chat_id from `.env` (loaded at init, never hardcoded).
- Design note: the old IPv4 monkey-patch is preserved as a private `_force_ipv4()` context manager to avoid the `Network is unreachable` error.

#### 2.7 `core/server_manager/` — Server Switching & sing-box Config

**Files:**
- `server_switcher.py` — `ServerSwitcher`
- `config_sanitizer.py` — `SingBoxConfigSanitizer`
- `config_deployer.py` — `ConfigDeployer`

**ServerSwitcher**:
- `switch(shell, fs, server_name: str) -> ServerSwitchResult` — looks up `server_name` in `ServersConfig`, finds matching outbound in profile JSON by tag, resolves server hostname to IP, updates `"vless-out"` tag in the outbounds array, writes to `/etc/sing-box/config.json`, restarts sing-box service. Returns old and new server names.
- `list_servers() -> list[ServerInfo]` — returns all configured servers with country, IP, status.
- `current(fs) -> ServerInfo` — reads current config, extracts active server tag.

**SingBoxConfigSanitizer**:
- `sanitize(fs, config_path: str) -> bool` — removes incompatible fields: `experimental.statistics`, `predefined` DNS, `batch` DNS → udp/local, `name` in rules, `default` in urltest/selector, `path` in remote rule_sets.

**ConfigDeployer**:
- `deploy(fs, shell, profile_path: str, dest_path: str) -> None` — copies profile → dest, runs sanitizer, restarts sing-box.

#### 2.8 `core/orchestrator.py` — Top-Level Lifecycle

Thin sequencer, ~50 lines. Replaces old `run_main_loop()` monster:

```python
class VpnOrchestrator:
    def __init__(self, deps: VpnDependencies): ...
    
    def bootstrap(self) -> None:
        """One-time setup: config deploy → topology → routing → firewall → tunnel."""
        # 1. Deploy & sanitize sing-box config
        # 2. Discover topology (gateway, interface)
        # 3. Resolve server IPs
        # 4. Configure routing (tun0, rules, RU bypass)
        # 5. Configure firewall (NAT, MSS, sysctl)
        # 6. Start tun2socks
    
    def run_forever(self) -> None:
        """Watchdog loop. Blocks until SIGTERM/SIGINT."""
        self.bootstrap()
        self.watchdog.run(self)
    
    def shutdown(self) -> None:
        """Graceful teardown: stop tunnel, clear routing, clear firewall."""
```

### Phase 3 — CLI (`src/vpn/cli/`)

Built with `click`. Entry point registered in `pyproject.toml` as `vpn`.

```
src/vpn/cli/
├── __init__.py
├── main.py          # Click group: vpn
├── server.py        # vpn server {change,list,current}
├── status.py        # vpn status (health, tunnel, routing summary)
├── logs.py          # vpn logs {tail, errors}
└── bypass.py        # vpn bypass {add,remove,list}
```

**Commands:**

| Command | Behavior |
|---|---|
| `vpn server list` | Print table: name, country, IP, port |
| `vpn server current` | Print active server name + IP |
| `vpn server change --name barguzin` | Switch to Баргузин, restart sing-box + tunnel |
| `vpn status` | Gateway, interface, tun0 state, last health check, uptime |
| `vpn logs tail` | Stream last N log lines |
| `vpn logs errors` | Show ERROR/CRITICAL from last hour |
| `vpn bypass add --domain example.com` | Add to bypass.yaml, re-apply routes |
| `vpn bypass remove --domain example.com` | Remove from bypass.yaml, re-apply routes |
| `vpn restart` | Full restart (same as watchdog recovery) |
| `vpn emergency-reset` | Wipe all rules, routes, tun0 — restore clean network |

### Phase 4 — Adapter Interfaces & Implementations

#### Protocol interfaces (`src/vpn/core/ports.py`):

```python
from typing import Protocol, runtime_checkable
from subprocess import CompletedProcess
from dataclasses import dataclass

@dataclass
class PopenHandle:
    pid: int
    poll: Callable[[], int | None]
    terminate: Callable[[], None]
    kill: Callable[[], None]
    wait: Callable[[float], int]

@runtime_checkable
class ShellPort(Protocol):
    def run(self, cmd: str, *, capture: bool = False, timeout: int = 20) -> CompletedProcess | None: ...

@runtime_checkable  
class FilesystemPort(Protocol):
    def read_text(self, path: str) -> str: ...
    def read_json(self, path: str) -> dict: ...
    def write_text(self, path: str, content: str) -> None: ...
    def write_json(self, path: str, data: dict) -> None: ...
    def exists(self, path: str) -> bool: ...
    def copy(self, src: str, dst: str) -> None: ...
    def makedirs(self, path: str) -> None: ...

@runtime_checkable
class HttpPort(Protocol):
    def post(self, url: str, data: bytes, timeout: int) -> None: ...

@runtime_checkable
class SubprocessPort(Protocol):
    def popen(self, args: list[str]) -> PopenHandle: ...
```

#### Adapter implementations (`src/vpn/adapters/`):

```
src/vpn/adapters/
├── __init__.py
├── system/
│   ├── __init__.py
│   ├── shell.py         # ShellPort: subprocess.run wrapper
│   ├── filesystem.py    # FilesystemPort: open/json/os.path/shutil
│   └── subprocess.py    # SubprocessPort: subprocess.Popen wrapper → PopenHandle
├── http/
│   ├── __init__.py
│   └── urllib_http.py   # HttpPort: urllib.request.urlopen wrapper
└── aconit/
    └── __init__.py       # user's adapter (preserved)
```

### Phase 5 — Docker Packaging

**Dockerfile** at repo root:

```dockerfile
FROM ubuntu:22.04

# Runtime deps
RUN apt-get update && apt-get install -y \
    curl iproute2 iptables tun2socks python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install sing-box (latest release)
# … download + install sing-box binary …

# Python app
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY src/ src/
COPY config/ config/
COPY data/ data/

ENTRYPOINT ["vpn"]
```

Run with: `docker run --net=host --cap-add=NET_ADMIN --name vpn -d vpn:latest`

The `--net=host` and `NET_ADMIN` capability are required because the container manipulates the host's network stack (iptables, ip routes, tun0).

### Phase 6 — RU Subnet Updater (standalone service)

The old `ru_updater.py` becomes a simple adapter script triggered by systemd timer on the host (NOT inside Docker — it needs to write to a shared volume):

```
src/vpn/adapters/ru_updater/
├── __init__.py
└── update.py
```

```python
def update_ru_cache(fs: FilesystemPort, http: HttpPort, cache_path: str) -> int:
    """Fetches RU IPv4 subnets, writes to cache_path. Returns count of subnets."""
```

### Phase 7 — Justfile for Local Dev & Deploy

```justfile
# Run locally (no Docker, for dev)
dev:
    uv run python -m vpn

# Docker build & push
docker-build:
    docker build -t vpn:latest .

# Deploy to Asus
deploy:
    docker save vpn:latest | ssh asus "docker load && docker stop vpn 2>/dev/null; docker run --net=host --cap-add=NET_ADMIN --name vpn -d --restart=always vpn:latest"

# CLI on remote Asus
shell:
    ssh asus "docker exec -it vpn vpn {{command}}"

# Server switch from local
change-server server:
    just shell "server change --name {{server}}"
```

## Critical Files & Anchors

- `src/vpn/config/paths.py` — PROJECT_ROOT discovery, `load_paths_config()`, dynamic `__getattr__` for YAML keys. **All** other modules import paths from here. Follow entsoe `paths.py` exactly.
- `src/vpn/config/config_loader.py` — `@cache`-decorated facade: `get_config()` master + delegator getters. The `VpnConfig` composed dataclass holds all sub-configs.
- `src/vpn/core/routing/rule_manager.py` — the priority constants `PRIO_SERVER_IPS=1` through `PRIO_CATCHALL=30`. These numbers are load-bearing: DNS must be < 8 (WireGuard), LAN at 10-12, catch-all at 30.
- `src/vpn/core/server_manager/server_switcher.py` — `switch()` is the core of the CLI's `vpn server change` command. Must match outbound tags from `servers.yaml` to entries in profile JSON.
- `src/vpn/core/ports.py` — Protocol definitions. Every core class type-hints against these, never against concrete adapters.
- `src/vpn/logger/exceptions.py` — `VpnError` hierarchy. Core modules raise these; CLI catches and formats them.

## Verification

1. **Config loading:** `cd /home/donald_trump/developer/vpn && uv run python -c "from vpn.config.config_loader import get_app_config; print(get_app_config())"` — prints `AppConfig(tag='hiddify-vpn', table_id='100', …)`.

2. **Server list:** `uv run vpn server list` — prints 11 servers with names, countries, IPs.

3. **Server switch (dry-run):** Mock the ShellPort adapter, run `ServerSwitcher.switch("barguzin")`, verify it selects the correct outbound tag from profile JSON.

4. **Docker build:** `docker build -t vpn:latest .` succeeds, `docker run --rm vpn:latest vpn server list` prints server table.

5. **Integration on Asus:** After deploy, `vpn status` shows gateway, interface, tunnel state. `vpn server change --name sirokko` switches to German server, connectivity check passes (`curl https://ifconfig.me` shows German IP).

## Assumptions & Contingencies

- **sing-box binary is baked into the Docker image** (not relying on host-installed sing-box). If sing-box must remain host-installed, remove it from Dockerfile and mount `/usr/bin/sing-box` and `/etc/sing-box/` as volumes.
- **The profile keys JSON** (`data/profile_keys_akonit_24_07_2026.json`) is the SSOT for VLESS outbounds. Server tags in `config/servers.yaml` MUST match the `"tag"` field in that JSON. If profile JSON is updated with new servers, `servers.yaml` must be updated too.
- **Telegram token goes in `.env`** as `VPN_TELEGRAM_TOKEN` and `VPN_TELEGRAM_CHAT_ID`. `NotificationConfig` reads from `os.environ`, NOT from YAML.
- **The `adapters/aconit/` directory** is the user's custom adapter — left as-is with `__init__.py`.
- **RU subnet cache** is fetched by a separate systemd timer on the host (not inside Docker), writing to a shared volume mounted at `/cache` in the container. If Docker cannot access host filesystem, run the updater as a sidecar container.
- **Old scripts** (`vless_updater.py`, `gemini_check_vpn.py`, `dadya_vanya.py`, old `vpn_daemon.py`) are NOT ported. They remain in the repo root for reference only. The new system replaces all their functionality.
