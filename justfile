default:
    @just --list

# === Build ===
build:
    docker build -t vpn:latest .

# === Test ===
test:
    uv run pytest -m "not integration" -v

test-all:
    uv run pytest -v

# === Deploy to Asus (local, via cable) ===
deploy tag:
    #!/bin/bash
    docker build -t vpn:{{tag}} -t vpn:latest .
    docker tag vpn:{{tag}} asus:5000/vpn:{{tag}}
    docker push asus:5000/vpn:{{tag}}
    scp compose.yml asus:/opt/vpn/compose.yml
    ssh asus "cd /opt/vpn && TAG={{tag}} docker compose up -d && docker image prune -a -f --filter 'until=24h'"

# === Verify ===
verify:
    ssh asus 'docker exec vpn vpn-internal status'

# === Logs ===
logs:
    ssh asus 'tail -f /var/log/syslog | grep --line-buffered vpn'

# === Server Management ===
change-server server:
    ssh asus "docker exec vpn vpn-internal server change --name {{server}}"

# # === Test ===
# test:
#     uv run pytest -m "not integration" -v --cov=src --cov-fail-under=80 
