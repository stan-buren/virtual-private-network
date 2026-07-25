# Phase 10 — Clean Fix of All Werner Bugs (revised)

## Context

Phase 9 edits introduced 9 bugs: missing catch-all, missing _watch_process, broken server.change, missing server.list/current, duplicate disable_ipv6, hatchling, silent bootstrap crash, bypass_loader signature break, anti-loop rules not reapplied on switch.

## Fixes

### Files to fix: orchestrator.py, machine.py, events.py, Dockerfile, __main__.py

### orchestrator.py
- ✅ Add `add_catchall(table_id)` + `set_default(table_id)` after `load_batch`
- ✅ Add `asyncio.create_task(_watch_process(...))` after sing-box `popen`
- ✅ Remove duplicate `disable_ipv6_wan()` from routing step
- ✅ Verify `_bypass_loader.load_all()` call signature matches actual method

### machine.py (_dispatch)
- ✅ Add `server.list` + `server.current` handlers
- ✅ Rewrite `server.change`: use `restart_service=False`, kill old sing-box (guarded), start new via proper subprocess, restart tun2socks, re-apply anti-loop bypass rules
- ✅ Guard: `if ctx.singbox is not None: ctx.singbox.kill()`

### __main__.py
- ✅ Wrap `asyncio.create_task(orchestrator.bootstrap(...))` in try/except → post `SINGBOX_DIED` on failure

### events.py
- ✅ Remove `SINGBOX_START_TIMEOUT = 10`

### Dockerfile
- ✅ Remove `pip3 install hatchling` line, keep `--no-build-isolation`

## Verification

1. `docker build --no-cache` succeeds
2. Deploy: tun0 UP, SOCKS5 listening, 8500+ routes in table 100
3. `vpn server list` shows 11 servers
4. `vpn server change ...` changes IP, anti-loop rules re-applied
5. Bootstrap crash → SINGBOX_DIED posted → state machine reacts
