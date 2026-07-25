# Phase 9 — Port Conflict Isolation & Bootstrap Resilience

## Context

Container bootstrap hangs when sing-box ports (3065, 3066, 3067) are occupied by old processes. Root cause: bootstrap runs as background `asyncio.create_task()` → failure invisible to state machine. `_wait_for_port` hangs forever because ports won't free themselves. Fix: cleanup.sh kills old processes before start, bootstrap stays as `create_task` but state reacts to events, `_wait_for_port` removed.

## Approach

### Step 1 — Update cleanup.sh with port-cleanup

```bash
# Order matters: systemctl first, then pkill
systemctl stop vpn-hiddify 2>/dev/null || true
systemctl stop sing-box 2>/dev/null || true
sleep 1
pkill -9 sing-box 2>/dev/null || true
pkill -9 tun2socks 2>/dev/null || true
sleep 1
for port in 3065 3066 3067; do
    ss -tlnp | grep -q ":$port " && echo "WARNING: port $port still occupied" || true
done
```

Deploy to `/opt/vpn/cleanup.sh` on Asus via MCP SSH.

### Step 2 — Bootstrap via create_task, state reacts to events

Keep `asyncio.create_task()` (non-blocking — shell commands are synchronous), but make BootstrappingState wait for `BOOTSTRAP_DONE` via event queue. IPC stays responsive.

In `BootstrappingState.on_enter()`:
```python
self._bootstrap_task = asyncio.create_task(
    self.machine._orchestrator.bootstrap(ctx, events)
)
```

In `BootstrappingState.handle()`:
- `BOOTSTRAP_DONE` → HealthyState
- `SINGBOX_DIED` → RestartingState (reuse same event, no separate `SINGBOX_START_TIMEOUT`)

In orchestrator `bootstrap()`: **remove `_wait_for_port()` entirely.** Step 2 becomes: start sing-box → register `_watch_process` → continue to topology.

In `__main__.py`: remove `asyncio.create_task(orchestrator.bootstrap(...))`, just `await machine.run()`.

### Step 3 — Rebuild, redeploy, verify

```bash
DOCKER_BUILDKIT=0 docker build -t vpn:latest .
docker tag && docker push
ssh asus '/opt/vpn/cleanup.sh && cd /opt/vpn && docker compose up -d'
sleep 10
ssh asus 'ss -tlnp | grep 3066'
ssh asus 'docker exec vpn vpn-internal server change zonda'
```

## Verification

1. Container HEALTHY within 10s
2. `vpn server change zonda` returns in <3s
3. `vpn server change barguzin` returns in <3s

## Critical Files

- `/opt/vpn/cleanup.sh` — systemctl stop → pkill → port check
- `src/vpn/core/orchestrator.py` — remove `_wait_for_port`
- `src/vpn/core/state_machine/states/bootstrapping.py` — create_task bootstrap, handle events
- `src/vpn/__main__.py` — `await machine.run()` only
