<div align="center">

# Virtual Private Network — Self-Healing Docker Orchestrator

### *From 934 lines of spaghetti to hexagonal event-driven architecture with Dagger CI/CD.*

A VPN daemon that survives crashes, switches servers in seconds, and deploys with a single command — no GitHub, no cloud, no manual ssh.

<br/>

<!-- ═══════════════════════ TECH STACK ═══════════════════════ -->

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-NET_ADMIN-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![sing-box](https://img.shields.io/badge/sing--box-VLESS_Reality-00BFA5?style=for-the-badge)
![Click](https://img.shields.io/badge/CLI-Click-4B8BBE?style=for-the-badge)

![asyncio](https://img.shields.io/badge/asyncio-Event_Driven-7D3C98?style=for-the-badge&logo=python&logoColor=white)
![Dagger](https://img.shields.io/badge/Dagger-CI/CD_Pipeline-00ADD8?style=for-the-badge&logo=dagger&logoColor=white)
![just](https://img.shields.io/badge/task_runner-just-9E75FF?style=for-the-badge)
![JSON-RPC](https://img.shields.io/badge/IPC-JSON--RPC_Unix_Socket-FF6F00?style=for-the-badge)

<br/>

<!-- ═══════════════════════ VITALS ═══════════════════════ -->

![Tests](https://img.shields.io/badge/tests-165_passed-brightgreen?style=flat-square)
![Coverage](https://img.shields.io/badge/coverage-≥80%25-green?style=flat-square)
![Coverage gate](https://img.shields.io/badge/commit_gate-≥80%25_coverage-blue?style=flat-square)
![Python](https://img.shields.io/badge/python-3651_lines-blue?style=flat-square&logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/deploy-1_command-2496ED?style=flat-square&logo=docker&logoColor=white)

<br/>

<b>
<a href="#-the-problem">Problem</a> ·
<a href="#-architecture">Architecture</a> ·
<a href="#-state-machine">State Machine</a> ·
<a href="#-project-structure">Structure</a> ·
<a href="#-cicd-pipeline">CI/CD</a> ·
<a href="#-quick-start">Quick Start</a> ·
<a href="#-cli-reference">CLI</a>
</b>

</div>

<br/>

---

> ***Legenda*** The old VPN daemon was 934 lines of hardcoded spaghetti: secrets in source, `while True: sleep; check; if fail` watchdog, no provider abstraction, no tests. Every change risked breaking production. So we threw it away and rebuilt from scratch — hexagonal architecture, event-driven state machine, full test suite, and a CI/CD pipeline that deploys with one command.

---

<br>

## 🎯 The Problem

<div align="center">
<table>
<tr>
<td width="50%" align="center">

### 🔥 What We Had

**934-line `vpn_daemon.py`. Secrets in source. `time.sleep()` watchdog. Zero tests.**

Every new idea → rewrite from scratch → more variants → chaos.

Multiple versions of the same daemon lying around: `vpn_daemon.py`, `vpn-hiddify-28-05-2026/`, `vless_updater.py`, `gemini_check_vpn.py`, `dadya_vanya.py`...

</td>
<td width="50%" align="center">

### 🏗️ What We Built

| Requirement | Implementation |
|---|---|
| 🔌 Provider-agnostic | Hexagonal Ports & Adapters |
| 🔄 Self-healing | Event-driven state machine (6 states) |
| 🧪 Tested | 165 tests, ≥80% coverage gate |
| 🚀 One-command deploy | Dagger CI/CD → Docker Registry → Asus |
| 🛑 Fail-closed | Per-state timeouts, crash-guarded bootstrap |
| 📡 Full observability | Structured logging, syslog over TCP |
| 🔧 Runtime control | JSON-RPC CLI over Unix socket |
| 🏷️ Versioned | `YYYYMMDD-HHMMSS-<hash>` immutable images |

</td>
</tr>
</table>
</div>

<br>

## 🏗️ Architecture

### Hexagonal Core — Provider-Agnostic by Design

The core knows nothing about "Akonit", "sing-box", or any VPN provider. It defines **Ports** (Protocol interfaces). Adapters implement them. Switching providers means writing a new adapter — zero changes to core.

```mermaid
flowchart LR
    subgraph CORE["Core (ports.py)"]
        VpnProviderPort["VpnProviderPort"]
        ShellPort["ShellPort"]
        FilesystemPort["FilesystemPort"]
        SubprocessPort["SubprocessPort"]
        HttpPort["HttpPort"]
    end

    subgraph ADAPTERS["Adapters"]
        Akonit["akonit/provider.py<br/>VLESS Reality, 11 servers<br/>sing-box config generation"]
        System["system/<br/>shell, filesystem,<br/>subprocess wrappers"]
        HTTP["http/<br/>urllib adapter"]
    end

    subgraph DOMAIN["Core Business Modules"]
        Orchestrator["Orchestrator<br/>7-step bootstrap sequencer"]
        Topology["Topology<br/>gateway discovery,<br/>DNS resolution"]
        Routing["Routing<br/>ip rules, table 100,<br/>RU bypass (8658 routes)"]
        Firewall["Firewall<br/>NAT, MSS clamp,<br/>sysctl"]
        Tunnel["Tunnel<br/>tun2socks,<br/>SOCKS5 bridge"]
        Health["Health<br/>curl-based checker,<br/>randomized intervals"]
        Notify["Notification<br/>Telegram alerts,<br/>IPv4-forced HTTP"]
        Server["Server Manager<br/>switch, list,<br/>config sanitizer"]
    end

    Akonit --> VpnProviderPort
    System --> ShellPort
    System --> FilesystemPort
    System --> SubprocessPort
    HTTP --> HttpPort

    Orchestrator --> VpnProviderPort
    Orchestrator --> ShellPort
    Orchestrator --> FilesystemPort
    Orchestrator --> SubprocessPort

    Orchestrator --> Topology
    Orchestrator --> Routing
    Orchestrator --> Firewall
    Orchestrator --> Tunnel
    Orchestrator --> Server
    Health --> ShellPort
    Notify --> HttpPort
```

### Runtime Topology

```mermaid
flowchart TB
    subgraph HP["Build Machine (HP)"]
        Dagger["Dagger CLI<br/>test → build → deploy"]
        Registry["Docker Registry<br/>192.168.0.131:5000"]
        Source["Source Code<br/>Python 3.12 + uv"]
    end

    subgraph ASUS["Router / VPN Host (Asus)"]
        Container["Docker Container<br/>--net=host --cap-add=NET_ADMIN"]
        subgraph Inside["Inside Container"]
            Daemon["Python Daemon<br/>State Machine + IPC"]
            SingBox["sing-box<br/>VLESS Reality<br/>SOCKS5 :3066"]
            Tun2Socks["tun2socks<br/>tun0 ↔ SOCKS5 bridge"]
        end
        Host["Host Network Stack<br/>ip rules, table 100, iptables"]
    end

    subgraph Internet["Internet"]
        VLESS["VLESS Reality Servers<br/>11 nodes across 7 countries"]
    end

    Dagger -->|"build + push"| Registry
    Dagger -->|"ssh deploy"| ASUS
    Registry -->|"docker pull"| Container

    Daemon -->|"manages"| SingBox
    Daemon -->|"manages"| Tun2Socks
    Daemon -->|"configures"| Host

    Tun2Socks -->|"TCP/UDP"| SingBox
    SingBox -->|"VLESS Reality"| VLESS

    Host -->|"catch-all priority 30 → table 100 → tun0"| Tun2Socks
```

### 7-Step Bootstrap Sequence

```mermaid
flowchart LR
    S1["1. Deploy Config<br/>profile → sanitize →<br/>/etc/sing-box/config.json"] -->
    S2["2. Start sing-box<br/>+ process watcher<br/>+ topology discovery"] -->
    S4["4. Routing<br/>tun0, server/DNS/LAN bypass,<br/>RU cache (8658 routes),<br/>catch-all priority 30"] -->
    S5["5. Firewall<br/>NAT MASQUERADE,<br/>MSS clamp 1360,<br/>ip_forward + IPv6 disable"] -->
    S6["6. Tunnel<br/>tun2socks → SOCKS5 :3066,<br/>RU subnet updater"] -->
    S7["7. BOOTSTRAP_DONE<br/>→ HEALTHY state"]
```

<br>

## 🔄 State Machine

6 states. Asyncio event-driven. No polling. No `while True: sleep`.

```mermaid
stateDiagram-v2
    [*] --> BOOTSTRAPPING

    BOOTSTRAPPING --> HEALTHY: BOOTSTRAP_DONE
    BOOTSTRAPPING --> RESTARTING: SINGBOX_DIED
    BOOTSTRAPPING --> FAILED: TIMEOUT (60s)

    HEALTHY --> DEGRADED: HEALTH_FAIL (1st)
    HEALTHY --> RESTARTING: SINGBOX_DIED / TUNNEL_DIED

    DEGRADED --> HEALTHY: HEALTH_OK
    DEGRADED --> RESTARTING: HEALTH_FAIL (3rd consecutive)

    RESTARTING --> HEALTHY: BOOTSTRAP_DONE
    RESTARTING --> FAILED: RESTART_TIMEOUT (10s)

    FAILED --> [*]: sys.exit(1)
    STOPPED --> BOOTSTRAPPING: vpn start

    note right of HEALTHY
        Health checker: randomized 25-55s
        Telegram alert on 2nd fail
    end note

    note right of RESTARTING
        Kill sing-box + tun2socks
        Restart both, wait 2s for port
    end note
```

### Per-State Timeouts

Every state sets an `asyncio.Task` timeout on entry. If the expected event never arrives, the state machine transitions to FAILED — no silent hangs.

| State | Timeout | On Expiry |
|---|---|---|
| BOOTSTRAPPING | 60s | → FAILED |
| RESTARTING | 10s | → FAILED |
| DEGRADED | — | Wait for next health check |
| HEALTHY | — | Idle, waits for events |

<br>

## 🔧 CLI over JSON-RPC

CLI runs inside the container, accessible from the host via a shell wrapper:

```bash
# /usr/local/bin/vpn on Asus host
exec docker exec -i vpn vpn-internal "$@"
```

Communication: **JSON-RPC 2.0 over Unix socket** (`/var/run/vpn.sock`). No HTTP, no ports, no auth — local IPC only.

```mermaid
sequenceDiagram
    participant H as Host Terminal
    participant W as /usr/local/bin/vpn
    participant C as Container CLI (Click)
    participant S as Unix Socket
    participant D as Daemon State Machine

    H->>W: vpn server change zonda
    W->>C: docker exec vpn vpn-internal server change zonda
    C->>S: {"method":"server.change","params":{"name":"zonda"}}
    S->>D: dispatch → switcher.switch() → kill old sing-box → start new → restart tun2socks
    D-->>S: {"result": "Зонда - Польша"}
    S-->>C: result
    C-->>H: Switched to: Зонда - Польша
```

<br>

## 🚀 CI/CD Pipeline

**Zero cloud dependencies.** Local Docker Registry on the router. Python pipeline script orchestrated via `just`.

```
$ just pipeline
```

```mermaid
flowchart LR
    subgraph HP["Build Machine"]
        Test["just test<br/>pytest ≥80% coverage gate"]
        Build["just build<br/>docker build + tag + push<br/>version: YYYYMMDD-HHMMSS-hash"]
        Deploy["just deploy<br/>scp compose.yml<br/>ssh → docker compose down<br/>→ TAG=v123 up -d<br/>→ health-check (10×2s)"]
    end

    subgraph Asus["Asus Router"]
        Registry["Docker Registry :5000"]
        Container["vpn container<br/>HEALTHY check"]
    end

    Test -->|"✓ 165 passed"| Build
    Build -->|"push :version + :latest"| Registry
    Deploy -->|"pull + restart"| Container
    Container -->|"HEALTHY?"| Deploy
```

### Versioning

`YYYYMMDD-HHMMSS-<7-char git hash>` — immutable, traceable, zero-config.

```bash
$ just build
20260725-183000-abc1234   ← printed + tagged + pushed

# Rollback to previous build:
$ ssh asus "cd /opt/vpn && TAG=20260725-120000-def5678 docker compose up -d"
```

### justfile commands

| Command | What it does |
|---|---|
| `just test` | Local pytest (fast, no Docker) |
| `just test-container` | Containerized pytest via Dagger SDK |
| `just build` | Docker build + push to asus:5000 with version tag |
| `just deploy VERSION` | SSH deploy with health-check |
| `just pipeline` | test-container → build → deploy (full CI/CD) |
<br>

## 📂 Project Structure

```
vpn/
├── 📄 README.md                          ← YOU ARE HERE
├── 📄 pyproject.toml                     ← Python project: Click, pytest, Dagger deps
├── 📄 justfile                           ← Task runner: test/build/deploy/pipeline
├── 📄 compose.yml                        ← Docker Compose: host network, NET_ADMIN, tun device
├── 📄 Dockerfile                         ← Python 3.12-slim + sing-box + tun2socks
├── 📄 .env.example                       ← Secrets template
│
├── 🐍 src/vpn/                           ← PYTHON SOURCE (3651 lines)
│   ├── __main__.py                       ← Entry point: wire adapters → state machine → asyncio.run()
│   │
│   ├── config/                           ← Config SSOT (YAML → frozen dataclasses)
│   │   ├── paths.py                      ← PROJECT_ROOT discovery (3-tier fallback)
│   │   ├── config_loader.py              ← @cache facade
│   │   └── core/                         ← App, Network, Health, Tunnel, Notification,
│   │                                       Servers, Bypass, VpnRoutes configs
│   │
│   ├── core/                             ← HEXAGONAL CORE
│   │   ├── ports.py                      ← ALL Protocol interfaces (Shell, FS, Subprocess, Http, VpnProvider)
│   │   ├── events.py                     ← EventType enum + VpnEvent dataclass
│   │   ├── orchestrator.py               ← 7-step bootstrap sequencer (~180 lines)
│   │   │
│   │   ├── state_machine/                ← EVENT-DRIVEN STATE MACHINE
│   │   │   ├── machine.py                ← VpnStateMachine: event queue, transitions, IPC server
│   │   │   ├── context.py                ← RuntimeContext: gateway, singbox handle, fail streak, route_ips
│   │   │   └── states/
│   │   │       ├── bootstrapping.py      ← Config deploy → topology → routing → firewall → tunnel
│   │   │       ├── healthy.py            ← Health checker running, tunnel operational
│   │   │       ├── degraded.py           ← Health failing, notifying Telegram
│   │   │       ├── restarting.py         ← Kill + restart sing-box + tun2socks
│   │   │       ├── failed.py             ← Final Telegram alert → sys.exit(1)
│   │   │       └── stopped.py            ← Clean shutdown, traffic goes direct
│   │   │
│   │   ├── topology/                     ← Network discovery + DNS resolution
│   │   ├── routing/                      ← ip rules, policy routing, RU bypass (8658 routes)
│   │   ├── firewall/                     ← NAT MASQUERADE, MSS clamp, sysctl
│   │   ├── tunnel/                       ← tun2socks process management
│   │   ├── health/                       ← Curl-based connectivity checker
│   │   ├── notification/                 ← Telegram alerts (IPv4-forced)
│   │   ├── server_manager/               ← Server switching, sing-box config deploy/sanitize
│   │   └── ru_updater/                   ← Background task: fetch RU IPv4 subnets every 24h
│   │
│   ├── cli/                              ← CLI (Click + JSON-RPC over Unix socket)
│   │   ├── main.py                       ← Click group: server, status, bypass, route, stop, start
│   │   └── ipc.py                        ← JSON-RPC client → /var/run/vpn.sock
│   │
│   ├── adapters/                         ← PORT IMPLEMENTATIONS
│   │   ├── akonit/provider.py            ← VpnProviderPort: 11 VLESS Reality servers, sing-box config,
│   │   │                                     emoji tag normalization, remote→local rule_set conversion
│   │   ├── system/                       ← ShellPort, FilesystemPort, SubprocessPort
│   │   └── http/                         ← HttpPort (urllib)
│   │
│   └── logger/                           ← Structured logging (scoped "vpn", propagate=False)
│
├── 🧪 tests/                             ← TEST SUITE (165 tests, ≥80% coverage)
│   ├── test_akonit_provider.py           ← Emoji normalization, config generation, sanitizer
│   ├── test_state_machine.py             ← All 6 states, transitions, IPC dispatch
│   ├── test_cli.py                       ← Click commands, JSON-RPC integration
│   ├── test_orchestrator.py              ← Bootstrap sequencer
│   ├── test_routing.py                   ← RuleManager, RouteTable, TunInterface
│   └── ... (10 more test files)
│
├── ⚙️ config/                            ← YAML CONFIGURATION
│   ├── app.yaml                          ← Provider, table_id, service names
│   ├── servers.yaml                      ← 11 servers (name → outbound tag)
│   ├── network.yaml                      ← tun0 IP/MTU, DNS servers, LAN subnets
│   ├── health.yaml                       ← Health check targets, intervals, thresholds
│   ├── tunnel.yaml                       ← SOCKS5 proxy settings
│   ├── notification.yaml                 ← Telegram event templates
│   ├── bypass.yaml                       ← Domains/subnets bypassing VPN
│   └── vpn-routes.yaml                   ← Domains/wildcards/subnets forced through VPN
│
├── 📦 data/                              ← STATIC DATA
│   ├── profile_keys_akonit_24_07_2026.json  ← VLESS Reality profile (11 outbounds)
│   ├── geoip-ru.srs                      ← Pre-cached Russian IP rule set
│   ├── geosite-ru.srs                    ← Pre-cached Russian domain rule set
│   └── tun2socks                         ← Statically-linked tun2socks binary
│
├── 🚀 ci/                                ← CI/CD PIPELINE
│   └── main.py                           ← Dagger pipeline: test() → build() → deploy()
│
├── 📋 docs/                              ← DOCUMENTATION
│   ├── plans/                            ← Architecture plans (Phase 0–13)
│   └── how-grilling-changed-the-way-ai-wrote-plans.md  ← ADR-012: AI-assisted planning
│
└── 🔒 .github/workflows/                 ← GitHub Actions (optional, offline-first)
    ├── ci.yml                            ← pytest + docker build + smoke tests
    └── security.yml                      ← Trivy vulnerability scan
```

<br>

## 🛡️ Key Design Decisions

### 1. Emoji Tag Normalization

Akonit profile tags carry emoji suffixes (`🧠 ✂️`, `(Без рекламы) ✂️`) that change between profile updates. `servers.yaml` uses human-readable aliases. The solution: `_normalize_tag()` strips all emoji via regex, normalizes both sides of every comparison. Server switching works for all 11 servers, regardless of emoji-version drift.

### 2. `copy.deepcopy` — Protected Profile Cache

`_load_profile()` caches the profile JSON in memory. `sanitize_config()` mutates it in-place. Without `copy.deepcopy()`, the second `server.change` operates on the already-mutated dict where `urltest_out` references are gone. Fix: `build_singbox_config()` deep-copies before modifying.

### 3. `stderr=None` — Visible Errors

Original subprocess adapter set `stderr=subprocess.DEVNULL`. sing-box crashes were invisible — zombie processes, no logs. Changed to `stderr=None` (inherit parent). Every sing-box `FATAL` now appears in Docker logs.

### 4. Offline-First CI/CD

No GitHub Actions, no cloud builders. Dagger runs locally, pushes to a Docker Registry on the router. The pipeline works even with VPN down — the only network dependency is `python:3.12-slim` base image (cached after first pull).

<br>

## 📋 CLI Reference

| Command | What it does |
|---|---|
| `vpn server list` | Table: name, country, host, port (11 servers) |
| `vpn server current` | Active server name |
| `vpn server change <name>` | Switch to barguzin/zonda/gregal/... — restarts sing-box + tun2socks |
| `vpn status` | Gateway, interface, tun0 state, uptime |
| `vpn restart` | Force state machine RESTARTING transition |
| `vpn stop` | Kill all processes, remove ip rules, flush table 100, clean firewall. Traffic goes direct. |
| `vpn start` | Idempotent bootstrap: mini-reset + full 7-step sequence |
| `vpn bypass add --domain <d>` | Add domain to VPN bypass list + instant ip rule |
| `vpn bypass remove --domain <d>` | Remove domain from bypass |
| `vpn bypass list` | Show current bypass domains |
| `vpn route add --domain <d>` | Force domain through VPN tunnel (DNS resolved on daemon) |
| `vpn route add --subnet <cidr>` | Force subnet through VPN |
| `vpn route add --wildcard <p>` | Wildcard pattern (applied on next restart) |
| `vpn route remove --domain <d>` | Remove from forced-VPN list + ip route |
| `vpn route list` | Show all forced-VPN entries |

<br>

## 🚦 Quick Start

### Prerequisites

- Python 3.12+, Docker, [uv](https://docs.astral.sh/uv/)
- Asus router with Docker and local registry on port 5000
- `sing-box` VLESS Reality profile in `data/`

### Local Development

```bash
git clone <repo>
cd vpn
uv sync --dev

# Run tests
just test

# Build Docker image
just build

# Full pipeline: test → build → deploy
just pipeline
```

### Deploy to Asus

```bash
# One command — builds, pushes to Asus registry, deploys with health-check
just pipeline

# Or step by step:
just test                    # pytest ≥80% coverage
just build                   # docker build + push to asus:5000
just deploy 20260725-183000-abc1234  # ssh → pull → restart → HEALTHY check
```

### Running on Asus

```bash
# Check status
vpn status

# List all 11 VPN servers
vpn server list

# Switch to Netherlands
vpn server change gregal

# Verify IP changed
curl -s ifconfig.me/ip

# Stop VPN (traffic goes direct)
vpn stop

# Start again
vpn start
```

<br>

## 📊 Performance

| Metric | Value |
|---|---|
| Bootstrap time | ~1.2 seconds |
| Server switch | <3 seconds |
| SOCKS5 latency | ~50ms idle |
| RU bypass routes | 8,658 subnets |
| Docker image size | ~250 MB |
| Memory footprint | ~60 MB (daemon + sing-box + tun2socks) |

<br>

## 🙏 Acknowledgments

- **[sing-box](https://github.com/SagerNet/sing-box)** — Universal proxy platform
- **[tun2socks](https://github.com/xjasonlyu/tun2socks)** — Layer 3 tunnel to SOCKS5 bridge
- **[Dagger](https://dagger.io/)** — CI/CD as code
- **[Matt Pocock's grilling skill](https://github.com/mattpocock/skills)** — Adversarial architecture review methodology
- **AI-assisted development** — Three-party consilium: architect + griller AI + sysadmin AI (see [ADR-012](docs/how-grilling-changed-the-way-ai-wrote-plans.md))

<br>

<div align="center">

### *Built with hexagonal architecture, tested with 165 tests, deployed with Dagger.*

</div>
