"""CI/CD pipeline for the VPN project — standalone, no external dependencies.

Usage:
    python ci/main.py test      # pytest with coverage gate (Dagger container)
    python ci/main.py build     # build + push a versioned image to the HP registry
    python ci/main.py deploy    # roll the image out onto the ASUS k3s cluster
    python ci/main.py pipeline  # test -> build -> deploy (full pipeline)

    deploy accepts --version <tag> (default: latest)
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

# ── deployment targets ───────────────────────────────────────────────────────
REGISTRY = "192.168.0.93:5000"          # registry address the k3s node pulls from
REGISTRY_PUSH = "localhost:5000"         # docker pushes via localhost (trusted by default)
ASUS_SSH = "donald_trump@192.168.0.131"  # k3s node that runs the vpn pod
NAMESPACE = "vpn"
DEPLOYMENT = "vpn"
MANIFEST = Path("deploy/vpn-k8s.yaml")

_USAGE = "Usage: python ci/main.py [test|build|deploy|pipeline] [--version TAG]"


def _version() -> str:
    """Generate a version tag: YYYYMMDD-HHMMSS-<7-char git hash>."""
    now = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    sha = subprocess.run(
        ["git", "rev-parse", "--short=7", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return f"{now}-{sha}"


async def _get_client():
    """Obtain a Dagger client connection (for containerized operations)."""
    from typing import cast

    import dagger as _dagger

    return cast(_dagger.Client, await _dagger.Connection())


async def test() -> str:
    """Run pytest in a clean Python 3.12 container with an >=80% coverage gate."""
    async with await _get_client() as client:
        return await (
            client.container()
            .from_("python:3.12-slim")
            .with_directory("/app", client.host().directory("."))
            .with_workdir("/app")
            .with_exec(
                [
                    "pip", "install", "--no-cache-dir",
                    "pytest", "pytest-asyncio", "pytest-cov", "pytest-mock",
                    "pyyaml", "click", "python-dotenv", "hatchling",
                ]
            )
            .with_exec(["pip", "install", "--no-build-isolation", "--no-deps", "."])
            .with_exec(
                [
                    "pytest",
                    "-m", "not integration",
                    "--cov=src",
                    "--cov-fail-under=80",
                    "-v",
                ]
            )
            .stdout()
        )


async def build() -> str:
    """Build a versioned Docker image and push it to the HP registry.

    Tags both :<version> and :latest.  Pushes to the registry under
    localhost (which Docker trusts by default); the k3s node pulls the same
    repository over the LAN IP.

    Returns:
        The generated version tag string.
    """
    version = _version()
    local = f"vpn:{version}"
    for cmd in [
        ["docker", "build", "-t", local, "."],
        ["docker", "tag", local, f"{REGISTRY_PUSH}/vpn:{version}"],
        ["docker", "push", f"{REGISTRY_PUSH}/vpn:{version}"],
        ["docker", "tag", local, f"{REGISTRY_PUSH}/vpn:latest"],
        ["docker", "push", f"{REGISTRY_PUSH}/vpn:latest"],
    ]:
        subprocess.run(cmd, check=True)
    print(version)
    return version


def _secret_yaml(env_text: str) -> str:
    """Render a vpn-env Secret manifest from a dotenv file's contents."""
    lines = [
        "apiVersion: v1",
        "kind: Secret",
        "metadata:",
        "  name: vpn-env",
        f"  namespace: {NAMESPACE}",
        "type: Opaque",
        "stringData:",
    ]
    for raw in env_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        lines.append(f"  {key.strip()}: {json.dumps(value.strip())}")
    return "\n".join(lines) + "\n"


def _ssh(remote: str, *, input_text: str | None = None) -> subprocess.CompletedProcess:
    """Run a command on the ASUS node over SSH."""
    return subprocess.run(
        ["ssh", ASUS_SSH, remote],
        input=input_text,
        text=True,
        capture_output=True,
    )


def _health_check() -> None:
    """Verify the pod's tunnel really carries traffic (not just a log line)."""
    remote = (
        "P=$(kubectl -n vpn get pod -l app=vpn -o jsonpath='{.items[0].metadata.name}'); "
        "kubectl -n vpn exec $P -- sh -c "
        "'pgrep -f sing-box >/dev/null && pgrep -f tun2socks >/dev/null && "
        "ss -ltn | grep -q 3066 && curl -4 -s -m 15 https://ifconfig.me/ip'"
    )
    last = ""
    for _ in range(12):
        result = _ssh(remote)
        exit_ip = (result.stdout or "").strip()
        if result.returncode == 0 and exit_ip:
            print(f"health OK — tunnel exit {exit_ip}")
            return
        last = result.stderr or result.stdout or ""
        time.sleep(5)
    raise RuntimeError(f"health check failed: {last}")


async def deploy(version: str | None = None) -> str:
    """Deploy a versioned image to the ASUS k3s cluster.

    1. Ensure the namespace and the vpn-env Secret exist.
    2. Apply the rendered manifest (image pinned to the version tag).
    3. Wait for the rollout and verify the tunnel carries traffic.

    Args:
        version: Image tag to deploy. Defaults to 'latest'.
    """
    version = version or "latest"
    image = f"{REGISTRY}/vpn:{version}"

    ns = "kubectl create namespace vpn --dry-run=client -o yaml | kubectl apply -f -"
    if _ssh(ns).returncode != 0:
        raise RuntimeError("failed to ensure namespace")

    env_text = Path(".env").read_text(encoding="utf-8")
    if _ssh("kubectl apply -f -", input_text=_secret_yaml(env_text)).returncode != 0:
        raise RuntimeError("failed to apply vpn-env secret")

    manifest = MANIFEST.read_text(encoding="utf-8").replace("__IMAGE__", image)
    applied = _ssh("kubectl apply -f -", input_text=manifest)
    if applied.returncode != 0:
        raise RuntimeError(f"manifest apply failed: {applied.stderr}")
    print(applied.stdout.strip())

    rollout = _ssh(
        f"kubectl -n {NAMESPACE} rollout status deployment/{DEPLOYMENT} --timeout=180s"
    )
    if rollout.returncode != 0:
        raise RuntimeError(f"rollout failed: {rollout.stderr or rollout.stdout}")
    print(rollout.stdout.strip())

    _health_check()
    print(f"deployed {image}")
    return version


async def pipeline() -> str:
    """Run the full pipeline: test -> build -> deploy. Fails fast."""
    print("=== TEST ===")
    print(await test())

    print("=== BUILD ===")
    version = await build()

    print(f"=== DEPLOY {version} ===")
    await deploy(version)

    return f"Pipeline complete: {version}"


async def main() -> None:
    """CLI dispatcher — route argv to the right function."""
    if len(sys.argv) < 2:
        print(_USAGE)
        sys.exit(1)

    command = sys.argv[1]

    if command == "test":
        print(await test())
    elif command == "build":
        print(await build())
    elif command == "deploy":
        version = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--version" else None
        print(await deploy(version))
    elif command == "pipeline":
        print(await pipeline())
    else:
        print(f"Unknown command: {command}")
        print(_USAGE)
        sys.exit(1)


if __name__ == "__main__":
    import anyio

    anyio.run(main)

