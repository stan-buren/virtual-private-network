# VPN Orchestrator Docker Image
# Runs sing-box + tun2socks + event-driven daemon in one container.

FROM python:3.12-slim

# Runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    iproute2 \
    iptables \
    ca-certificates \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip3 install --no-cache-dir click pyyaml python-dotenv

# Install sing-box binary.
# PINNED ON PURPOSE: the provider profile still ships legacy DNS server formats,
# which sing-box 1.14.0 removed ("legacy DNS server formats ... removed in
# sing-box 1.14.0"). Do NOT bump past 1.12.x until the profile is migrated to the
# new DNS server formats and route.default_domain_resolver is set — verify with:
#   sing-box check -c <generated config.json>
ARG SING_BOX_VERSION=1.12.17
RUN curl -fsSL -o /tmp/sing-box.tar.gz \
    "https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/sing-box.tar.gz -C /tmp \
    && install -m 0755 /tmp/sing-box-*/sing-box /usr/local/bin/sing-box \
    && rm -rf /tmp/sing-box*

# Install tun2socks — the gVisor-based stack that bridges tun0 to the SOCKS proxy.
# Pinned by version AND sha256: this binary is where a nil-dereference in the
# bundled gVisor build used to kill the tunnel, so the upgrade path must live in
# the image, not in a hand-copied file in data/ (which is gitignored).
# v2.7.0 was tried and reverted: its process starts and logs its banner, but it
# never brings the externally-created tun0 to carrier-up, so the table-100
# default route stays "linkdown" and the host silently stops tunnelling (seen on
# HP and ASUS, 2026-10-16). Adopt 2.7 only together with its new device contract
# (let tun2socks own the device) and a real end-to-end check.
ARG TUN2SOCKS_VERSION=2.6.0
ARG TUN2SOCKS_SHA256=2c4d9891ca898ecb2b582d158612d44c66793008328852b3465b77828c867e77
RUN curl -fsSL -o /tmp/tun2socks.zip \
      "https://github.com/xjasonlyu/tun2socks/releases/download/v${TUN2SOCKS_VERSION}/tun2socks-linux-amd64.zip" \
    && echo "${TUN2SOCKS_SHA256}  /tmp/tun2socks.zip" | sha256sum -c - \
    && python3 -m zipfile -e /tmp/tun2socks.zip /tmp \
    && install -m 0755 /tmp/tun2socks-linux-amd64 /usr/local/bin/tun2socks \
    && rm -rf /tmp/tun2socks*

# Pre-cached rule sets
COPY data/geoip-ru.srs data/geosite-ru.srs /var/lib/sing-box/

# Ookla Speedtest CLI (network metrics for vpn server speedtest)
RUN curl -fsSL -o /tmp/speedtest.tgz https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-x86_64.tgz && tar -xzf /tmp/speedtest.tgz -C /tmp && install -m 0755 /tmp/speedtest /usr/local/bin/speedtest && rm -rf /tmp/speedtest*

# Application
WORKDIR /app
COPY pyproject.toml .
COPY README.md .
COPY src/ src/
COPY config/ config/
COPY data/ data/
RUN pip3 install --no-cache-dir hatchling && pip3 install --no-build-isolation --no-deps --no-cache-dir .
RUN mkdir -p /etc/sing-box /app/cache /app/logs /var/lib/sing-box

ENV PYTHONUNBUFFERED=1
ENV PROJECT_ROOT=/app
ENTRYPOINT ["python3", "-m", "vpn"]
