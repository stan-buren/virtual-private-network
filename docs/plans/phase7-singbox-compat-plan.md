# Phase 7 — Sing-Box Config Compatibility & Process Management

## Context

Old sing-box on Asus: **v1.12.17** — works with provider config. Docker container: v1.11.6 — fails with `json: unknown field "type"`. Root cause: version mismatch. Fix: use 1.12.17. Also: provider config is COMPLETE — no template needed. Also: sing-box must be started as a managed subprocess with port-wait to prevent race conditions.

## Facts (verified)

- Working sing-box version: **1.12.17** (on Asus)
- Provider config (`profile_keys_akonit_24_07_2026.json`): complete sing-box config — 14 outbounds, 3 inbounds, 17 DNS servers, route rules, experimental block
- Our `SINGBOX_TEMPLATE` in `provider.py`: dead code — provider config SSOT, template unused in actual deploy
- sing-box is NOT started by the orchestrator — must be added as bootstrap step 2

## Approach

### Step 1 — sing-box 1.12.17 in Dockerfile

Replace `v1.11.6` → `v1.12.17`. Add `ARG SING_BOX_VERSION`. Ensure `data/` is copied into the image:

```dockerfile
COPY data/ /app/data/   # includes profile_keys JSON (provider config SSOT)
```
```dockerfile
ARG SING_BOX_VERSION=1.12.17
RUN curl -fsSL -o /tmp/sing-box.tar.gz \
    "https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/sing-box.tar.gz -C /tmp \
    && install -m 0755 /tmp/sing-box-*/sing-box /usr/local/bin/sing-box \
    && rm -rf /tmp/sing-box*
```

### Step 2 — Remove SINGBOX_TEMPLATE, use provider config as SSOT

Delete `SINGBOX_TEMPLATE` dict from `src/vpn/adapters/akonit/provider.py`.

Rewrite `build_singbox_config()`:
```python
def build_singbox_config(self, server_name: str) -> str:
    """Load provider config, set active server via urltest_out.default, sanitize."""
    config = self._load_profile()
    tag = self._servers_config.servers[server_name].tag
    for ob in config.get("outbounds", []):
        if ob.get("type") == "urltest":
            ob["default"] = tag
            break
    sanitized = self.sanitize_config(config)
    return json.dumps(sanitized, indent=2)
```

### Step 3 — Start sing-box in orchestrator bootstrap

Add step 2 in `bootstrap()`: after deploy → start sing-box → wait port → then topology/routing/firewall/tunnel.

New bootstrap order:
1. Deploy config
2. Start sing-box (`popen(["sing-box", "run", "-c", config, "-D", "/var/lib/sing-box"])`)
3. Register process watcher (fires `SINGBOX_DIED`)
4. Wait for SOCKS5 port (`_wait_for_port("127.0.0.1", 3066, timeout=10)`)
5. Discover topology
6. Configure routing
7. Configure firewall
8. Start tun2socks + background tasks, post `BOOTSTRAP_DONE`

Add helper method to orchestrator:
```python
async def _wait_for_port(self, host: str, port: int, timeout: int) -> None:
    """Block until TCP port accepts connections or timeout expires."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=2
            )
            writer.close()
            return
        except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
            await asyncio.sleep(0.5)
    raise VpnConnectionError("Port %s:%d not ready after %ds" % (host, port, timeout))
```

Add `_watch_process` to orchestrator for sing-box monitoring (same pattern as tun2socks).

Also add two new event types to `src/vpn/core/events.py`:
```python
SINGBOX_DIED = 5       # (already exists — verify)
SINGBOX_START_TIMEOUT = 10  # new: sing-box failed to start within timeout
```

### Step 4 — Deploy & Debug Cycle

Same cycle as Phase 6, adapted for sing-box changes:

```bash
# 1. Build & push
docker build -t vpn:latest .
docker tag vpn:latest 192.168.0.131:5000/vpn:latest
docker push 192.168.0.131:5000/vpn:latest

# 2. Deploy
scp compose.yml asus:/opt/vpn/
ssh asus '/opt/vpn/cleanup.sh && cd /opt/vpn && docker compose up -d'

# 3. Diagnostic
ssh asus 'docker ps | grep vpn'
ssh asus 'docker exec vpn vpn-internal server list'
ssh asus 'ip link show tun0 | grep -q UP && echo "tun0: UP" || echo "tun0: DOWN"'
ssh asus 'ss -tlnp | grep 3066'
ssh asus 'curl -sI --max-time 8 https://google.com'
ssh asus 'docker exec vpn sing-box check -c /etc/sing-box/config.json'
ssh asus 'grep vpn /var/log/syslog | tail -50'

# 4. Rollback if needed
ssh asus "cd /opt/vpn && TAG=<previous> docker compose up -d"
```
