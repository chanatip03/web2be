FROM node:20-slim

# --- install basic deps ---
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    git \
    python3 \
    python3-pip \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# --- install Snyk CLI (official way) ---
RUN npm install -g snyk

# --- verify ---
RUN snyk --version

# --- runtime config ---
WORKDIR /scan

# Snyk CLI uses HOME for cache / engine
ENV HOME=/tmp
ENV SNYK_CFG_DIR=/tmp/.config/snyk

ENTRYPOINT ["snyk"]
