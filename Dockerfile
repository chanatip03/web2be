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
# Install Snyk CLI
# =========================
RUN curl https://static.snyk.io/cli/latest/snyk-linux \
    -o /usr/local/bin/snyk \
    && chmod +x /usr/local/bin/snyk

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
