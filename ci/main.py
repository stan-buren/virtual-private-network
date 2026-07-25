"""CI/CD pipeline for VPN project — standalone, no external dependencies.

Usage:
    python ci/main.py test     # Run pytest with coverage gate (uses Dagger container)
    python ci/main.py build    # Build + push versioned Docker image to Asus registry
    python ci/main.py deploy   # SSH to Asus -> pull -> restart -> health-check
    python ci/main.py pipeline # test -> build -> deploy (full pipeline)

    deploy accepts --version <tag> (default: latest)
"""

from __future__ import annotations

import datetime
import subprocess
import sys


_USAGE = "Usage: python ci/main.py [test|build|deploy|pipeline] [--version TAG]"
def _version() -> str:
    """Generate version tag: YYYYMMDD-HHMMSS-<7-char git hash>."""
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
    """Run pytest in a clean Python 3.12 container with >=80% coverage gate."""
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
    """Build versioned Docker image and push to Asus local registry.

    Tags both :<version> and :latest so Asus can pin a specific version
    or always pull the latest.  Does NOT use Dagger — calls docker CLI directly.

    Returns:
        The generated version tag string.
    """
    version = _version()
    for cmd in [
        ["docker", "build", "-t", f"vpn:{version}", "."],
        ["docker", "tag", f"vpn:{version}", f"192.168.0.131:5000/vpn:{version}"],
        ["docker", "push", f"192.168.0.131:5000/vpn:{version}"],
        ["docker", "tag", f"vpn:{version}", "192.168.0.131:5000/vpn:latest"],
        ["docker", "push", "192.168.0.131:5000/vpn:latest"],
    ]:
        subprocess.run(cmd, check=True)
    print(version)
    return version


async def deploy(version: str | None = None) -> str:
    """Deploy a versioned image to the Asus router via SSH.

    1. mkdir -p /opt/vpn/cache     — ensure volume dir exists
    2. scp compose.yml             — always push latest compose config
    3. docker compose down          — stop running container
    4. TAG=<version> docker compose up -d  — start with new image
    5. Health-check: poll docker logs for 'HEALTHY' (up to 10 attempts x 2s)
    6. Fail loudly if HEALTHY never appears

    Args:
        version: Image tag to deploy. Defaults to 'latest'.
    """
    if version is None:
        version = "latest"

    # Push latest compose.yml so Asus always has devices + volumes
    subprocess.run(
        ["scp", "compose.yml", "donald_trump@192.168.0.131:/opt/vpn/compose.yml"],
        check=True,
    )

    remote = (
        "mkdir -p /opt/vpn/cache && cd /opt/vpn && docker compose down && "
        f"TAG={version} docker compose up -d && "
        "for i in $(seq 1 10); do "
        "  docker logs vpn --tail 3 2>/dev/null | grep -q HEALTHY && exit 0; "
        "  sleep 2; "
        "done; "
        "echo 'FATAL: container not healthy after 20s' >&2; exit 1"
    )
    cmd = f"ssh donald_trump@192.168.0.131 '{remote}'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "deploy failed")
    print(result.stdout or result.stderr)
    return version


async def pipeline() -> str:
    """Run the full pipeline: test -> build -> deploy.

    Fails fast: test failures block build, build failures block deploy.
    """
    print("=== TEST ===")
    print(await test())

    print("=== BUILD ===")
    version = await build()

    print(f"=== DEPLOY {version} ===")
    await deploy(version)

    return f"Pipeline complete: {version}"


async def main() -> None:
    """CLI dispatcher — route argv to the right function."""
    usage = "Usage: python ci/main.py [test|build|deploy|pipeline] [--version TAG]"
    if len(sys.argv) < 2:
        print(usage)
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
        print(usage)
        sys.exit(1)


if __name__ == "__main__":
    import anyio
    anyio.run(main)
