# Quick Fix: server.change hangs

## Context
`vpn server change` hangs because `ServerSwitcher.switch()` kills sing-box via `pkill` but doesn't restart it. The IPC response never returns because the process that would send it is dead.

## Fix
In `src/vpn/core/state_machine/machine.py:_dispatch()`:
- Change `server.change` to call `self._switcher.switch(name, restart_service=False)` — write config only, no kill
- Post `RESTART_REQUESTED` event — state machine handles restart properly via its own lifecycle
- Return result immediately

## Verification
`vpn server change zonda` returns within 2 seconds.
