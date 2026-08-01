#!/bin/bash
# ============================================================================
# vpn-emergency-cleanup — аварийная очистка сети без Docker
#
# Использовать когда:
#   - vpn-stop не работает (контейнер мёртв/в цикле перезапуска)
#   - После ребута остались ip rules / iptables / table 100 / tun0
#   - Интернет не работает из-за остатков VPN-правил
#
# Запуск:
#   sudo bash vpn-emergency-cleanup.sh
#
# Что делает:
#   1. Убивает контейнер VPN (если жив)
#   2. Удаляет tun0
#   3. Чистит ip rules приоритетов 1-30
#   4. Сбрасывает routing table 100
#   5. Чистит iptables NAT цепочку VPN_ASUS_OUTPUT
#   6. Чистит iptables mangle MSS clamp
#   7. Убивает остаточные процессы sing-box/tun2socks
#   8. Восстанавливает IPv6
#   9. Проверяет что интернет работает
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[CLEANUP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }

# ── 0. Проверка прав ──────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "Нужен sudo: sudo bash vpn-emergency-cleanup.sh"
    exit 1
fi

log "=== VPN Emergency Cleanup ==="

# ── 1. Убить Docker-контейнер (если жив) ──────────────────────────────────
if command -v docker &>/dev/null; then
    if docker ps -q --filter name=vpn | grep -q .; then
        log "[1/8] Killing VPN container..."
        docker stop vpn 2>/dev/null || true
        docker rm -f vpn 2>/dev/null || true
    else
        log "[1/8] VPN container not running — skip"
    fi
else
    warn "[1/8] Docker not found — skip container kill"
fi

# ── 2. Удалить tun0 ───────────────────────────────────────────────────────
log "[2/8] Removing tun0..."
ip link set dev tun0 down 2>/dev/null || true
ip tuntap del mode tun dev tun0 2>/dev/null || true

# ── 3. Очистить ip rules (приоритеты 1-30) ────────────────────────────────
log "[3/8] Clearing ip rules..."
# Priority 1 — может быть несколько (серверные bypass'ы)
while ip rule del priority 1 2>/dev/null; do :; done
# Priorities 2-30
for p in $(seq 2 30); do
    while ip rule del priority "$p" 2>/dev/null; do :; done
done

# ── 4. Сбросить routing table 100 ─────────────────────────────────────────
log "[4/8] Flushing routing table 100..."
ip route flush table 100 2>/dev/null || true

# ── 5. Очистить iptables NAT ──────────────────────────────────────────────
CHAIN="VPN_ASUS_OUTPUT"
log "[5/8] Cleaning iptables NAT chain '$CHAIN'..."
if command -v iptables &>/dev/null; then
    iptables -t nat -D POSTROUTING -j "$CHAIN" 2>/dev/null || true
    iptables -t nat -F "$CHAIN" 2>/dev/null || true
    iptables -t nat -X "$CHAIN" 2>/dev/null || true
else
    warn "[5/8] iptables not installed — skip (install with: sudo apt install iptables)"
fi

# ── 6. Очистить iptables mangle (MSS clamp) ───────────────────────────────
log "[6/8] Cleaning mangle MSS clamp..."
if command -v iptables &>/dev/null; then
    iptables -t mangle -D FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1360 2>/dev/null || true
else
    warn "[6/8] iptables not installed — skip"
fi

# ── 7. Убить процессы sing-box / tun2socks ────────────────────────────────
log "[7/8] Killing leftover sing-box/tun2socks processes..."
pkill -9 sing-box 2>/dev/null || true
pkill -9 tun2socks 2>/dev/null || true

# ── 8. Восстановить IPv6 ──────────────────────────────────────────────────
log "[8/8] Restoring IPv6..."
sysctl -w net.ipv6.conf.all.disable_ipv6=0 >/dev/null 2>&1 || true

# ── Проверка ──────────────────────────────────────────────────────────────
log ""
log "=== Verification ==="

# Проверяем ip rules
RULES_LEFT=$(ip rule show | grep -cE 'priority [0-9]+:' || true)
if [[ "$RULES_LEFT" -eq 0 ]]; then
    log "✅ ip rules: clean"
else
    warn "⚠️  $RULES_LEFT ip rules still present"
fi

# Проверяем table 100
ROUTES_IN_100=$(ip route show table 100 2>/dev/null | wc -l)
if [[ "$ROUTES_IN_100" -eq 0 ]]; then
    log "✅ Table 100: empty"
else
    warn "⚠️  $ROUTES_IN_100 routes in table 100"
fi

# Проверяем tun0
if ip link show tun0 &>/dev/null; then
    warn "⚠️  tun0 still exists"
else
    log "✅ tun0: removed"
fi

# Проверяем default route
DEFAULT_GW=$(ip route show default | awk '{print $3}')
log "✅ Default gateway: $DEFAULT_GW"

# Проверяем интернет
log ""
log "Testing internet connectivity..."
if curl -s --max-time 5 https://ifconfig.me/ip >/dev/null 2>&1; then
    IP=$(curl -s --max-time 5 https://ifconfig.me/ip)
    log "✅ Internet: OK (IP: $IP)"
else
    if ping -c 1 -W 3 1.1.1.1 >/dev/null 2>&1; then
        warn "⚠️  Ping works but HTTPS fails — check DNS/firewall"
    else
        err "❌ No internet! Check: ip route show default"
    fi
fi

log ""
log "=== Cleanup complete ==="
log "To restart VPN: cd /home/donald_trump/developer/vpn && just hp-up"
