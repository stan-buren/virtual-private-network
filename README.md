# 🛡️ VPN Orchestrator

[![CI](https://github.com/stan-buren/vpn/actions/workflows/ci.yml/badge.svg)](https://github.com/stan-buren/vpn/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12+-blue)
![Docker](https://img.shields.io/badge/docker-✔-2496ED)

**Event-driven sing-box VPN daemon with tun2socks bridging, hexagonal architecture, and provider-agnostic core.**

---

## Architecture

```mermaid
flowchart LR
    subgraph Provider["Provider Adapter (akonit/vanya/...)"]
        KEYS[VLESS Keys JSON]
    end

    subgraph Core["VPN Core (provider-agnostic)"]
        SM[State Machine<br/>BOOTSTRAPPING → HEALTHY → DEGRADED]
        ORCH[Orchestrator]
        ROUTING[Routing Engine]
        FW[Firewall Manager]
        HC[Health Checker]
    end

    subgraph Network["Network Layer"]
        SB[sing-box<br/>VLESS Reality]
        SOCKS[SOCKS5<br/>127.0.0.1:3066]
        T2S[tun2socks]
        TUN[tun0<br/>198.18.0.1/15]
    end

    KEYS --> SB
    SB --> SOCKS
    SOCKS --> T2S
    T2S --> TUN
    TUN --> ROUTING
    ROUTING --> FW
    SM --> ORCH
    ORCH --> ROUTING
    ORCH --> FW
    HC --> SM
```

## Deploy Topology

```mermaid
flowchart LR
    DEV[Dev Machine] -->|docker build| IMG[Docker Image]
    IMG -->|docker push| REG[Local Registry<br/>asus:5000]
    REG -->|docker pull| HOST[VPN Host]
    HOST -->|docker compose up| CONT[Container<br/>--net=host<br/>NET_ADMIN]

    CONT -->|syslog TCP| DEV
    DEV -->|ssh| HOST
```

## Quick Start

```bash
# Clone
git clone <repo-url>
cd vpn

# Build
docker build -t vpn:latest .

# Deploy (requires SSH access to VPN host)
just deploy 20260725-001
```

## CLI Reference

| Command | Description |
|---|---|
| `vpn server list` | List all 11 available VPN servers |
| `vpn server current` | Show currently active server |
| `vpn server change --name <name>` | Switch to a different server |
| `vpn status` | Show daemon status, gateway, tunnel state |
| `vpn logs` | View recent logs |
| `vpn bypass list` | Show current VPN bypass domains |
| `vpn bypass add --domain <domain>` | Add domain to bypass list |
| `vpn bypass remove --domain <domain>` | Remove domain from bypass list |
| `vpn restart` | Force full daemon restart |
| `vpn emergency-reset` | Wipe all rules, routes, tun0 |

## Configuration

All configuration lives in `config/*.yaml`. No hardcoded values in code.

| File | Purpose |
|---|---|
| `config/app.yaml` | Daemon tag, routing table ID, provider name |
| `config/network.yaml` | tun0 settings, DNS servers, LAN subnets, MSS |
| `config/health.yaml` | Health check targets, intervals, fail thresholds |
| `config/tunnel.yaml` | SOCKS5 proxy host/port, optional MacBook proxy |
| `config/notification.yaml` | Telegram event templates and retry settings |
| `config/servers.yaml` | CLI name → provider tag mapping (11 servers) |
| `config/bypass.yaml` | Domains/subnets to bypass the VPN |
| `config/vpn-routes.yaml` | Domains/wildcards/subnets forced through VPN |
| `config/paths.yaml` | Filesystem paths (all relative to project root) |

Secrets (Telegram token, chat ID) go in `.env` — never in YAML.

## State Machine

```mermaid
stateDiagram-v2
    [*] --> BOOTSTRAPPING
    BOOTSTRAPPING --> HEALTHY : BOOTSTRAP_DONE
    HEALTHY --> DEGRADED : HEALTH_FAIL × 1
    DEGRADED --> HEALTHY : HEALTH_OK
    DEGRADED --> RESTARTING : HEALTH_FAIL × 3
    RESTARTING --> HEALTHY : BOOTSTRAP_DONE
    RESTARTING --> FAILED : TIMEOUT
    FAILED --> [*] : sys.exit(1)

    note right of RESTARTING
        Restart sing-box
        Wait 2s for port
        Restart tun2socks
        Timeout: 10s
    end note

    note left of FAILED
        Telegram alert with last_error
        Docker restarts container
    end note
```

## Adding a New VPN Provider

1. Create `src/vpn/adapters/<provider>/provider.py`
2. Implement `VpnProviderPort` (defined in `src/vpn/core/ports.py`):
   - `list_servers() -> list[ServerInfo]`
   - `get_server(name) -> ServerInfo`
   - `build_singbox_config(server_name) -> str`
   - `sanitize_config(raw) -> dict`
3. Create `config/servers.yaml` registry for the new provider's servers
4. Change `provider: <name>` in `config/app.yaml`

Zero changes to core code.

---

**License:** Apache 2.0
