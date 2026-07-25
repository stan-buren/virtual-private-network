# Phase 5 — Tests, CI/CD, Deploy, Docs

## Context

The core architecture is built (~50 Python files, 9 YAML configs). Next: complete the daemon wiring (`VpnOrchestrator` + `__main__.py`), add 14 test files with ≥80% coverage gate, set up GitHub Actions CI (pytest + docker build + smoke tests), polish Justfile with docker compose deploy, delete old scripts, and write a professional README with Mermaid diagrams. CI verifies deployability; actual deploy stays local via cable.

## Approach

### Step 1 — Delete Old Code

Run `rm -rf` on: `vpn_daemon.py`, `vless_updater.py`, `gemini_check_vpn.py`, `dadya_vanya.py`, `ru_updater.py`, `logger.py`, `ru-updater.service`, `ru-updater.timer`, `vpn-hiddify.service`, `config_template.json`, `custom-bypass.txt`, `custom-bypass-bakk.txt`, `custom-vpn.txt`, `webui/`, old `README.md`, old `justfile`.

No archive — old code is in git history if needed.

### Step 2 — Create `.dockerignore`

```
__pycache__/
.mypy_cache/
.pytest_cache/
.git/
.github/
tests/
docs/
.env
```

### Step 3 — Create `compose.yml`

```yaml
services:
  vpn:
    image: localhost:5000/vpn:${TAG:-latest}
    container_name: vpn
    network_mode: host
    cap_add:
      - NET_ADMIN
    restart: unless-stopped
    logging:
      driver: syslog
      options:
        syslog-address: "tcp://${SYSLOG_HOST:-192.168.0.93}:514"
        syslog-facility: "local0"
        tag: "vpn"
```

### Step 4 — Create `VpnOrchestrator` and Complete `__main__.py`

Create `src/vpn/core/orchestrator.py`:

```python
class VpnOrchestrator:
    """Thin sequencer — wires core services, runs bootstrap, no business logic."""

    def __init__(self, deployer, topology_discovery, resolver, tun, rules,
                 route_table, bypass_loader, nat, mss, sysctl_mgr, tun2socks,
                 provider, notifier, ru_updater,
                 app_cfg, net_cfg, tunnel_cfg, bypass_cfg, vpn_routes_cfg, paths):
        # ... store all as self._x ...

    async def bootstrap(self, ctx: RuntimeContext, events: asyncio.Queue) -> None:
        # 1. Deploy config
        self._deployer.deploy()
        # 2. Discover topology
        topology = self._topology_discovery.discover()
        ctx.gateway = topology.gateway
        ctx.interface = topology.interface
        # 3. Routing
        self._tun.create()
        server_ips = self._resolver.resolve_all(...)
        for ip in server_ips:
            self._rules.add_server_bypass(ip)
        for i, dns_ip in enumerate(self._net_cfg.dns_servers):
            self._rules.add_dns_bypass(dns_ip, priority=PRIO_DNS_START + i)
        for subnet in self._net_cfg.lan_subnets:
            self._rules.add_lan_bypass(subnet, priority=PRIO_LAN_START)
        routes = self._bypass_loader.load_all(...)
        self._route_table.load_batch(routes, self._app_cfg.table_id)
        self._rules.add_torrent_bypass()
        self._rules.add_catchall(self._app_cfg.table_id)
        self._route_table.set_default(self._app_cfg.table_id)
        # 4. Firewall
        self._nat.apply(topology.interface)
        self._mss.apply()
        self._sysctl_mgr.enable_ip_forward()
        self._sysctl_mgr.disable_ipv6_wan()
        # 5. Start tunnel + background tasks
        proxy_url = f"socks5://{self._tunnel_cfg.socks5_host}:{self._tunnel_cfg.socks5_port}"
        ctx.tun2socks = await self._tun2socks.start(proxy_url)
        ctx.active_server = self._provider.current_server().name
        self._ru_updater_task = asyncio.create_task(self._ru_updater.run_forever())
        # 6. Signal done
        await events.put(VpnEvent(EventType.BOOTSTRAP_DONE))
```

Rewrite `src/vpn/__main__.py` as pure wiring: create adapters → create provider (AkonitProvider from config) → create core services → create orchestrator → create RuntimeContext + VpnStateMachine → `asyncio.run(machine.run())`.

### Step 5 — Tests (14 files, AAA pattern, ≥80% coverage gate)

Update `pyproject.toml` with pytest config:

```toml
[tool.pytest.ini_options]
addopts = ["-ra", "--strict-markers", "--tb=short",
    "--cov=src", "--cov-report=term-missing", "--cov-fail-under=80"]
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "unit: marks fast unit tests",
    "integration: marks tests requiring network or root",
]
```

Add dev deps: `pytest`, `pytest-cov`, `pytest-mock`, `pytest-asyncio`.

Create all 14 test files:

| File | What it tests |
|---|---|
| `tests/test_config_loader.py` | All 8 config dataclasses load from YAML |
| `tests/test_paths.py` | PROJECT_ROOT resolves, paths.yaml constants valid |
| `tests/test_logger.py` | VpnError hierarchy, JsonFormatter, scoped logger |
| `tests/test_events.py` | EventType enum, VpnEvent construction |
| `tests/test_state_machine.py` | All 5 state transitions, per-state timeouts, fail streak |
| `tests/test_orchestrator.py` | Bootstrap call order: deploy → topology → routing → firewall → tunnel → BOOTSTRAP_DONE |
| `tests/test_topology.py` | TopologyDiscovery, DnsResolver, ServerIpResolver (mocked shell) |
| `tests/test_routing.py` | Priority constants, TunInterface, RuleManager, RouteTable |
| `tests/test_bypass_loader.py` | RU cache parsing, domain resolution, wildcard expansion |
| `tests/test_notification.py` | TelegramNotifier formatting, IPv4 patch, retry |
| `tests/test_server_manager.py` | ServerSwitcher, ConfigDeployer (mocked provider) |
| `tests/test_adapters.py` | All 5 adapters implement their ports |
| `tests/test_akonit_provider.py` | 11 servers, build_singbox_config, sanitize_config |
| `tests/test_cli.py` | Click CLI: help, server list, server change |

### Step 6 — GitHub Actions CI

Create `.github/workflows/ci.yml`:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --dev
      - run: uv run pytest -m "not integration" -v --cov=src --cov-fail-under=80
  docker:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t vpn:ci-test .
      - run: |
          docker run --rm vpn:ci-test python3 -c "
          from vpn.config.config_loader import get_servers_config;
          assert len(get_servers_config().servers) == 11;
          print('OK: 11 servers loaded')
          "
      - run: docker run --rm vpn:ci-test vpn-internal --help
```

Three checks: unit tests with 80% coverage → docker build → smoke tests (imports + CLI). No ruff, no mypy (run locally if desired). No deploy to Asus from CI.

### Step 7 — Justfile (polished)

```justfile
default:
    @just --list

build:
    docker build -t vpn:latest .

test:
    uv run pytest -m "not integration" -v

test-all:
    uv run pytest -v

deploy tag:
    #!/bin/bash
    docker build -t vpn:{{tag}} -t vpn:latest .
    docker tag vpn:{{tag}} asus:5000/vpn:{{tag}}
    docker push asus:5000/vpn:{{tag}}
    scp compose.yml asus:/opt/vpn/compose.yml
    ssh asus "cd /opt/vpn && TAG={{tag}} docker compose up -d && docker image prune -a -f --filter 'until=24h'"

verify:
    ssh asus 'docker exec vpn vpn-internal status'
logs:
    ssh asus 'tail -f /var/log/syslog | grep --line-buffered vpn'

change-server server:
    ssh asus "docker exec vpn vpn-internal server change --name {{server}}"
```

### Step 8 — README.md

Professional README following n-cmapss-rul-mlops-factory pattern. Sections:

1. **Badges**: CI status, Python 3.12+, Docker
2. **Architecture**: Mermaid flowchart showing Provider → sing-box → SOCKS5 → tun2socks → tun0 → ip rules → routing table 100
3. **Deploy Topology**: Mermaid diagram showing Dev Machine → (build+pull) → Docker Registry → Asus Host (no hardcoded IPs — use labels like "Dev Machine", "Router/VPN Host")
4. **Quick Start**: `docker build`, `just deploy`
5. **CLI Reference**: Table of all commands with descriptions
6. **Configuration**: Table of YAML files with purpose
7. **State Machine**: Mermaid state diagram (BOOTSTRAPPING → HEALTHY → DEGRADED → RESTARTING → FAILED)
8. **Adding a Provider**: 4-step guide

### Step 9 — Copy Approved Plan

Write `local://vpn-core-adapters-plan.md` to `docs/plans/vpn-core-adapters-plan-approved.md` (new file — does NOT overwrite pre-grilling plan at `migrate-to-new-architecture-plan.md`).

## Verification

1. `uv run pytest -m "not integration" -v --cov=src` — all 14 test files pass, coverage ≥ 80%
2. `docker build -t vpn:latest .` — exits 0
3. `docker run --rm vpn:latest vpn-internal --help` — prints CLI help
4. `docker run --rm vpn:latest python3 -c "from vpn.config import get_servers_config; assert len(get_servers_config().servers) == 11"` — prints nothing (assertion passes)

## Critical Files & Anchors

- `src/vpn/core/orchestrator.py` — VpnOrchestrator class, ~50 lines, thin sequencer
- `src/vpn/__main__.py` — pure wiring, no business logic
- `.github/workflows/ci.yml` — pytest + docker build + smoke tests
- `compose.yml` — single-file deployment config
- `tests/test_state_machine.py` — verifies all 5 state transitions

## Assumptions & Contingencies

- **Coverage gate at 80%** — enforced by `--cov-fail-under=80` in pytest. If tests don't reach 80%, CI is red, deploy blocked.
- **Old code deleted, not archived** — available in git history if needed.
- **CI does NOT deploy** — only verifies code is safe to deploy. Actual deploy is manual `just deploy <tag>` from dev machine.
- **compose.yml copied to Asus** on each deploy — single 1KB file via scp.
- **No secrets in README** — no IP addresses, no tokens. Architecture diagrams use generic labels.
