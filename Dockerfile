FROM python:3.11-slim

# =========================
# Environment
# =========================
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# =========================
# System dependencies
# =========================
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# =========================
# Docker CLI (for docker run inside container)
# =========================
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
        https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# =========================
# Python dependencies
# =========================
COPY requirement.txt .
RUN pip install --no-cache-dir -r requirement.txt

# =========================
# Application source
# =========================
COPY app /app/app
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

# =========================
# Runtime directories (เฉพาะที่ scanner ใช้จริง)
# =========================
RUN mkdir -p \
    /app/data/submissions \
    /app/data/security_scan_results

# =========================
# Expose API
# =========================
EXPOSE 8000

# =========================
# Start FastAPI
# =========================
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
