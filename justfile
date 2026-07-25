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
