# Repository Guidelines

## Project Overview

VPN Orchestrator — a self-healing, event-driven VPN daemon in Docker. Manages sing-box VLESS Reality tunnels with tun2socks bridging, policy routing (RU bypass), and Telegram notifications. **Hexagonal architecture** — provider-agnostic core, pluggable adapters. Deployed on an Asus router via local Docker Registry, offline-first CI/CD.

## Architecture & Data Flow

```
Entry (__main__.py)
  └─ wire adapters (akonit, system, http)
  └─ wire core services (TopologyDiscovery, TunInterface, Routing, Firewall, Tunnel, Health, Notification, ServerManager)
  └─ VpnOrchestrator (7-step bootstrap sequencer)
  └─ VpnStateMachine (event queue + IPC server)
       └─ states/ (6 states: Bootstrapping → Healthy ⇄ Degraded → Restarting → Failed | Stopped)
```

**Key patterns:**
- **Ports & Adapters**: `src/vpn/core/ports.py` defines interfaces (ShellPort, SubprocessPort, VpnProviderPort, etc.). Adapters in `src/vpn/adapters/` implement them. Core NEVER imports adapters directly — injection at `__main__.py`.
- **Event-driven state machine**: `asyncio.Queue[VpnEvent]` consumed by `VpnStateMachine.run()`. Each state's `handle(event)` returns after transitioning. No polling.
- **Dependency injection**: `VpnOrchestrator.__init__()` takes all services as keyword-only constructor args. `VpnStateMachine.__init__()` takes optional mocked deps.
- **Immutable configs**: YAML → frozen dataclasses via `_from_yaml()` classmethod, cached via `@cache` in `config_loader.py`.

## Key Directories

| Path | Purpose |
|---|---|
| `src/vpn/core/` | Hexagonal core — orchestrator, state machine, routing, firewall, tunnel, health, topology, notification |
| `src/vpn/core/state_machine/` | machine.py + context.py + states/ (6 states) |
| `src/vpn/adapters/akonit/` | VpnProviderPort: sing-box profile parsing, config generation, emoji tag normalization |
| `src/vpn/adapters/system/` | ShellPort, FilesystemPort, SubprocessPort adapters |
| `src/vpn/adapters/http/` | HttpPort adapter (urllib) |
| `src/vpn/cli/` | Click CLI + JSON-RPC client (Unix socket) |
| `src/vpn/config/` | YAML SSOT → frozen dataclasses, paths.py resolution, config_loader facade |
| `src/vpn/logger/` | Scoped "vpn" logger, dual formatters (text/JSON), exception hierarchy |
| `ci/` | CI/CD pipeline script (test/build/deploy/pipeline) |
| `tests/` | 16 test files, 165 tests, pytest + asyncio + cov + mock |
| `config/` | YAML configs (gitignored — use `config/` on Asus or `config_env/` locally) |
| `data/` | Static binaries and profile data (gitignored except .srs files) |
| `docker/` | Docker build context artifacts |

## Development Commands

```bash
# Run all tests with coverage gate
just test                    # → uv run pytest -m "not integration" --cov=src --cov-fail-under=80 -v

# Build Docker image + push to Asus registry
just build                   # → uv run python ci/main.py build

# Deploy to Asus router
just deploy v1.2.3           # → scp compose.yml + ssh → docker compose down → TAG=v1.2.3 up -d → health-check

# Full CI/CD pipeline
just pipeline                # → test-container → build → deploy

# Run a single test file
uv run pytest tests/test_state_machine.py -v

# Run with specific marker
uv run pytest -m "unit" -v
uv run pytest -m "integration" -v   # requires VPN + root

# Install dev dependencies
uv sync --dev
```

## Code Conventions & Common Patterns

### Logging
```python
import logging
logger = logging.getLogger("vpn")

# CORRECT: %s placeholders
logger.info("Server %r switched, new tag: %s", name, tag)
logger.error("Bootstrap failed: %s", err)

# WRONG: f-strings in log calls
logger.info(f"Server {name} switched")  # NEVER do this
```

### Async patterns
- All state machine methods are `async def`
- `asyncio.Queue[VpnEvent]` for event bus — `await queue.put(event)` / `event = queue.get_nowait()`
- `asyncio.create_task()` for fire-and-forget background work (health checker, RU updater, process watcher)
- `asyncio.sleep(0)` to yield between bootstrap steps
- `anyio.run()` as the top-level runner in `ci/main.py`

### Dependency injection
```python
# Constructor injection — all keyword-only
class VpnOrchestrator:
    def __init__(self, *, deployer: ConfigDeployer, tun: TunInterface, ...):
        self._deployer = deployer
        self._tun = tun

# Optional mocked deps on state machine
class VpnStateMachine:
    def __init__(self, initial_state_cls, *, provider=None, shell=None, ...):
```

### Dataclass usage
- **Frozen** for configs and events: `@dataclass(frozen=True)` — immutable, hashable
- **Mutable** for runtime context: `@dataclass` — `ctx.fail_streak += 1` is normal
- Mutable dataclass fields MUST have defaults: `route_ips: dict[str, list[str]] = field(default_factory=dict)`

### Emoji tag normalization
```python
# src/vpn/adapters/akonit/provider.py
class AkonitProvider:
    @staticmethod
    def _normalize_tag(tag: str) -> str:
        tag = _EMOJI_RE.sub("", tag)
        tag = tag.replace("(Без рекламы)", "")
        return " ".join(tag.split()).strip()
```
ALWAYS normalize both sides of a tag comparison. Profile emoji suffixes drift between updates.

### Error handling
- `try/except Exception` with `logger.exception()` for crash-guarded blocks (bootstrap, process watchers)
- `raise KeyError(f"Server {name!r} not found")` — use `!r` in error messages
- Context: `ctx.last_error = "Human-readable error string"`
- States: `FailedState.on_enter()` → `sys.exit(1)` → Docker `--restart=unless-stopped`

### Naming conventions
- Config classes: `AppConfig`, `NetworkConfig`, `ServersConfig` — singular, PascalCase
- Adapters: `AkonitProvider`, `ShellAdapter`, `FilesystemAdapter` — PascalCase
- States: `BootstrappingState`, `HealthyState`, `StoppedState` — PascalCase with State suffix
- Event enum: `EventType.BOOTSTRAP_DONE`, `EventType.SINGBOX_DIED` — UPPER_SNAKE_CASE
- IPC methods: `"server.list"`, `"route.add"` — lowercase dotted strings
- Functions/Methods: `snake_case`
- Module files: `snake_case.py`

### Docstrings
- Google-style: one-line summary, blank line, `Args:` / `Returns:` / `Raises:`
- Public API: MUST have full docstrings
- Internal helpers: short `"""One-line."""` is fine

### Sanitize-then-use pattern
`build_singbox_config()` MUST `copy.deepcopy(profile)` before mutation. The profile cache is shared; the second mutation corrupts the cached copy.

## Important Files

| File | Role |
|---|---|
| `src/vpn/__main__.py` | Entry point — wires all adapters → orchestrator → state machine → asyncio.run() |
| `src/vpn/core/ports.py` | ALL protocol interfaces. The contract between core and adapters. |
| `src/vpn/core/orchestrator.py` | 7-step bootstrap: deploy → sing-box → topology → routing → firewall → tunnel → BOOTSTRAP_DONE |
| `src/vpn/core/state_machine/machine.py` | Event loop + IPC server (13 RPC methods) + state transitions |
| `src/vpn/core/state_machine/states/bootstrapping.py` | Most complex state — crash-guarded bootstrap, 60s timeout |
| `src/vpn/adapters/akonit/provider.py` | VLESS Reality adapter — config gen, emoji normalization, sanitizer |
| `src/vpn/config/paths.py` | Three-tier PROJECT_ROOT discovery (env → .project_root → parents[3]) |
| `config/servers.yaml` | Server registry: CLI name → outbound tag + country. MUST be kept in sync with profile. |
| `compose.yml` | Docker Compose: host network, NET_ADMIN, /dev/net/tun device, syslog |
| `ci/main.py` | Pipeline: `test()` (Dagger containerized), `build()` (docker push), `deploy()` (ssh + health-check) |
| `justfile` | Task runner: `just test`, `just build`, `just deploy`, `just pipeline` |

## Runtime/Tooling Preferences

- **Python**: 3.12+ (`.python-version`)
- **Package manager**: `uv` — `uv sync --dev`, `uv run`, `uv pip install`
- **Build system**: `hatchling` (PEP 621 in `pyproject.toml`)
- **Install**: `pip install --no-build-isolation --no-deps .` (hatchling pre-installed)
- **Docker**: `docker build --no-cache` (BuildKit caches stale source layers)
- **Docker Compose**: `docker compose` (not `docker-compose`), explicit `TAG=` env
- **OS**: Linux only — uses `AF_UNIX` sockets, `iproute2`, `iptables`, `/dev/net/tun`
- **sing-box**: v1.12.17 (pinned — provider config format dependent)
- **Version tags**: `YYYYMMDD-HHMMSS-<7-char git hash>` — zero-config, traceable
- **CI/CD**: Offline-first — local Docker Registry on Asus (192.168.0.131:5000), no GitHub dependency on deploy

## Testing & QA

### Framework
- **pytest** with `pytest-asyncio`, `pytest-cov`, `pytest-mock`
- Configuration in `pyproject.toml` `[tool.pytest.ini_options]`
- `pythonpath = ["src"]` — `from vpn.` imports work in tests
- Markers: `unit` (fast, no network), `integration` (needs VPN + root)

### Running tests
```bash
just test                                    # all unit tests + coverage gate
uv run pytest -m "not integration" -v        # same, verbose
uv run pytest -m "unit" -v                   # only unit tests
uv run pytest -k "IpcDispatch" -v            # filter by test name
```

### Coverage
- Gate: **≥80%** (enforced by `--cov-fail-under=80`)
- `just test` or `just pipeline` — both enforce the gate
- Current: 165 tests, ~80% coverage

### Test patterns
- **Mocking**: `unittest.mock.MagicMock` for services, `AsyncMock` for async methods
- **Fixtures**: `@pytest.fixture` for shared state machine mock setup
- **State transitions**: use `_patch_exit()` context manager + `_handle_event()` helper
- **CLI tests**: `CliRunner` + `patch("vpn.cli.main.ipc_call", return_value=...)`
- **IPC tests**: call `machine._dispatch("method", params)` directly with mocked deps
- **Config tests**: instantiate dataclass via `_from_yaml()`, verify field values

### Commit gate
- Pre-push: `just test` MUST pass
- CI (optional GitHub Actions): `.github/workflows/ci.yml` — pytest + docker build + smoke
- Security: `.github/workflows/security.yml` — Trivy + Gitleaks
