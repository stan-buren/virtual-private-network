default:
    @just --list

# === Test (local pytest, fast) ===
test:
    uv run pytest -m "not integration" --cov=src --cov-fail-under=80 -v

# === Test (Dagger containerized, reproducible) ===
test-container:
    uv run python ci/main.py test

# === Build (Docker build + push to Asus:5000) ===
build:
    uv run python ci/main.py build

# === Deploy (SSH to Asus, restart, health-check) ===
deploy VERSION="latest":
    uv run python ci/main.py deploy --version {{VERSION}}

# === Full pipeline: test-container -> build -> deploy ===
pipeline:
    uv run python ci/main.py pipeline

# === HP local: build image for HP (NOT pushed to registry) ===
hp-build:
    docker build -t vpn:latest .

# === HP local: start VPN on this machine ===
hp-up:
    docker compose -f compose.yml -f compose.hp.yml up -d

# === HP local: stop VPN (graceful via IPC, or force-kill) ===
hp-down:
    docker exec -i vpn vpn-internal stop 2>/dev/null || true
    docker compose -f compose.yml -f compose.hp.yml down --timeout 5 2>/dev/null || true
    @echo "If internet does not work, run: sudo bash scripts/vpn-emergency-cleanup.sh"

# === Emergency network cleanup (NO Docker required) ===
emergency-cleanup:
    sudo bash scripts/vpn-emergency-cleanup.sh

# === View VPN logs ===
logs:
    docker logs -f vpn
