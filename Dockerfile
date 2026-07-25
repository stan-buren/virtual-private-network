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

# Install sing-box binary — version pinned to match provider config compatibility
ARG SING_BOX_VERSION=1.12.17
RUN curl -fsSL -o /tmp/sing-box.tar.gz \
    "https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/sing-box.tar.gz -C /tmp \
    && install -m 0755 /tmp/sing-box-*/sing-box /usr/local/bin/sing-box \
    && rm -rf /tmp/sing-box*

# Copy statically-linked tun2socks binary
COPY data/tun2socks /usr/local/bin/tun2socks
RUN chmod +x /usr/local/bin/tun2socks

# Pre-cached rule sets
COPY data/geoip-ru.srs data/geosite-ru.srs /var/lib/sing-box/

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
