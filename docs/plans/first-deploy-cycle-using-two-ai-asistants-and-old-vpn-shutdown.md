# Phase 6 — Build, Deploy, Debug on Asus

## Context

Git is clean (v1.0 pushed). VPN is alive. Now: build Docker image with hermetic .srs files, fix sanitizer bug, deploy to Asus via MCP SSH, run diagnostic suite, iterate until stable.

## Approach

### Step 1 — Fix Sanitizer Logic

The bug: sanitizer blindly deletes `path` from remote rule_sets. Fix in `src/vpn/adapters/akonit/provider.py`:

```python
for rs in raw.get("route", {}).get("rule_set", []):
    if rs.get("type") == "remote":
        tag = rs["tag"]
        cache_path = "/var/lib/sing-box/%s.srs" % tag.replace(":", "-")
        if os.path.exists(cache_path):
            rs["type"] = "local"
            rs["path"] = cache_path
            rs.pop("url", None)
            rs.pop("download_detour", None)
            rs.pop("update_interval", None)
        # else: leave as remote — container has internet or will fail gracefully
```

Key: sanitizer **generates** cache path from tag (does not look for existing `path` field).
Formula: `/var/lib/sing-box/<tag-with-dashes>.srs`.

### Step 2 — Fetch .srs Files (one-time)

The `.srs` rule-set files exist on Asus at `/var/lib/sing-box/`. Copy them into the repo so Dockerfile can COPY them:

```bash
mkdir -p data/
scp asus:/var/lib/sing-box/geoip-ru.srs data/
scp asus:/var/lib/sing-box/geosite-ru.srs data/
```

### Step 3 — Docker Build (VPN ON)

**Pre-check VPN:** `curl -I --socks5-hostname 127.0.0.1:3066 --connect-timeout 5 https://google.com >/dev/null 2>&1 || echo "FATAL: VPN not reachable — aborting build"`

```bash
cd /home/donald_trump/developer/vpn
docker build -t vpn:latest .
docker tag vpn:latest asus:5000/vpn:latest
docker push asus:5000/vpn:latest
```

### Step 4 — Cleanup Script on Asus

Deploy `/opt/vpn/cleanup.sh` via MCP SSH — surgical cleanup, never `iptables -F`:

```bash
#!/bin/bash
set -e

# Stop old systemd services (idempotent — may not exist on second deploy)
systemctl is-active vpn-hiddify 2>/dev/null && systemctl stop vpn-hiddify || true
systemctl is-active sing-box 2>/dev/null && systemctl stop sing-box || true

# Stop old Docker container from previous deploy
docker stop vpn 2>/dev/null && docker rm vpn 2>/dev/null || true

# Remove tun0
ip link del tun0 2>/dev/null || true

# Only VPN priorities (1-30), leave the rest
for p in $(seq 1 30); do ip rule del priority $p 2>/dev/null || true; done

iptables -t nat -F VPN_ASUS_OUTPUT 2>/dev/null || true
iptables -t nat -X VPN_ASUS_OUTPUT 2>/dev/null || true
iptables -t mangle -F ts-postrouting 2>/dev/null || true
iptables -t mangle -X ts-postrouting 2>/dev/null || true
ip route flush table 100 2>/dev/null || true
echo "Cleanup complete."
```

### Step 5 — Deploy Container

```bash
# Ensure target directory exists
ssh asus 'mkdir -p /opt/vpn'

# Deploy cleanup script
scp scripts/cleanup.sh asus:/opt/vpn/cleanup.sh
ssh asus 'chmod +x /opt/vpn/cleanup.sh'

# Registry (idempotent)
ssh asus 'docker start registry 2>/dev/null || docker run -d -p 5000:5000 --restart=always --name registry registry:2'

# Wrapper (idempotent — only first deploy)
ssh asus 'test -f /usr/local/bin/vpn || sudo tee /usr/local/bin/vpn > /dev/null << "EOF"
#!/bin/bash
exec docker exec -i vpn vpn-internal "$@"
EOF
sudo chmod +x /usr/local/bin/vpn'

# Deploy
scp compose.yml asus:/opt/vpn/compose.yml
ssh asus '/opt/vpn/cleanup.sh && cd /opt/vpn && TAG=latest docker compose up -d'
```

### Step 6 — Diagnostic Suite

```bash
# 1. Container alive?
ssh asus 'docker ps | grep vpn'

# 2. VPN server list (11 servers expected)
ssh asus 'docker exec vpn vpn-internal server list'

# 3. tun0 up? (robust check)
ssh asus 'ip link show tun0 | grep -q UP && echo "tun0: UP" || echo "tun0: DOWN"'

# 4. SOCKS5 port listening?
ssh asus 'ss -tlnp | grep 3066'

# 5. Connectivity through VPN
ssh asus 'curl -sI --max-time 8 https://google.com'

# 6. sing-box config syntax check
ssh asus 'docker exec vpn sing-box check -c /etc/sing-box/config.json'

# 7. Logs (from syslog — NOT docker logs)
ssh asus 'grep vpn /var/log/syslog | tail -50'

# 8. Container logs (stdout fallback)
ssh asus 'docker logs vpn --tail 30 2>/dev/null || echo "(no docker logs — using syslog)"'
```

### Step 7 — Debug Cycle

```
1. Build fix → docker build && docker push
2. scp compose.yml asus:/opt/vpn/
3. ssh asus '/opt/vpn/cleanup.sh && cd /opt/vpn && TAG=latest docker compose up -d'
4. Diagnostic suite (Step 6)
5. OK → done | FAIL → fix → goto 1
```

### Step 8 — Rollback

```bash
ssh asus "cd /opt/vpn && TAG=<previous_tag> docker compose up -d"
```

## Verification

1. `docker build -t vpn:latest .` — succeeds with VPN on
2. `docker run --rm vpn:latest python3 -c "from vpn.config import get_servers_config; assert len(get_servers_config().servers) == 11"` — passes
3. After deploy: diagnostic suite all green
4. `ssh asus 'curl -sI https://google.com'` → HTTP 200

## Critical Files

- `src/vpn/adapters/akonit/provider.py` — `sanitize_config()` rule_set handling (generates cache path, does not blindly delete)
- `Dockerfile` — `COPY data/*.srs /var/lib/sing-box/` instead of curl
- `/opt/vpn/cleanup.sh` — surgical cleanup, preserves AdGuard Home and Docker networks
- `data/geoip-ru.srs`, `data/geosite-ru.srs` — pre-cached rule-set binaries, hermetic build

## Division of Responsibility

```
┌─ Werner (OpenClaw) ─────────────────────────────┐
│ • Ensures VPN is alive on HP before build       │
│ • Maintains cleanup.sh on ASUS                  │
│ • Fetches .srs files into repo (Step 2)         │
│ • Troubleshoots if diagnostics fail             │
└──────────────────────────────────────────────────┘
                     ↕
┌─ OMP (OhMyPie) ────────────────────────────────┐
│ • docker build && docker push (Step 3)          │
│ • Deploy via MCP SSH (Step 5)                   │
│ • Run diagnostic suite (Step 6)                 │
│ • OK → done / FAIL → alert Werner + rollback    │
└──────────────────────────────────────────────────┘
```
