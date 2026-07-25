# VPN Orchestrator Docker Image
# Runs sing-box + tun2socks + event-driven daemon in one container.

FROM ubuntu:22.04

# Runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    iproute2 \
    iptables \
    python3 \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install sing-box via official script
# (sing-box provides its own install script; we could also curl the binary)
RUN curl -fsSL https://sing-box.app/gpg.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/sagernet.gpg \
    && echo "deb [arch=amd64] https://deb.sagernet.org/ * *" > /etc/apt/sources.list.d/sagernet.list \
    && apt-get update && apt-get install -y sing-box && rm -rf /var/lib/apt/lists/*

# Install tun2socks
RUN apt-get update && apt-get install -y tun2socks && rm -rf /var/lib/apt/lists/*

# Application
WORKDIR /app
COPY pyproject.toml .
RUN pip3 install --no-cache-dir .

COPY src/ src/
COPY config/ config/
COPY data/ data/

# Create required directories
RUN mkdir -p /app/cache /app/logs

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python3", "-m", "vpn"]
