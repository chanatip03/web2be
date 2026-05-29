# WEB2 Backend API

A comprehensive FastAPI-based backend service for the WEB2 platform, featuring plagiarism detection, code analysis, security scanning, and student code deployment capabilities.

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Database](#database)
- [Security Scanning](#security-scanning)
- [Deployment](#deployment)
- [Development](#development)

## Overview

WEB2 Backend is a sophisticated educational platform API that enables instructors to manage student submissions, detect plagiarism, analyze code security, and deploy student applications. The system supports automated code scanning, plagiarism detection using JPlag, and security analysis through Snyk.

## Tech Stack

- **Framework**: FastAPI 0.128.0
- **Server**: Uvicorn 0.40.0
- **Database**: PostgreSQL 16
- **ORM**: SQLAlchemy 2.0.45
- **Authentication**: python-jose, PassLib, BCrypt
- **Cloud Storage**: AWS S3/CloudFlare R2
- **Testing**: Robot Framework
- **Security Scanning**: Snyk CLI
- **Java**: OpenJDK 26 (for JPlag)
- **Containerization**: Docker & Docker Compose

## Features

✅ **User Authentication & Authorization**
- JWT-based token authentication
- Password hashing with bcrypt
- Role-based access control

✅ **Student Submission Management**
- File upload and storage via R2
- ZIP archive extraction and processing
- Submission tracking and version control

✅ **Plagiarism Detection**
- JPlag integration for code similarity detection
- Background scheduler for batch processing
- Detailed plagiarism reports

✅ **Security Analysis**
- Snyk CLI integration for vulnerability scanning
- Automated security scan results storage

✅ **Code Deployment**
- Docker-based student code deployment
- Project and deployment data management
- Port management for preview instances

✅ **Email Notifications**
- SMTP-based email delivery
- User communication support

✅ **API Documentation**
- Auto-generated Swagger UI documentation
- ReDoc integration

## Prerequisites

- Docker & Docker Compose
- Python 3.11+
- PostgreSQL 16
- Java 26 (installed automatically in Docker)
- Git

## Installation

### Clone the Repository

```bash
git clone https://github.com/chanatip03/web2be.git
cd web2be
```

### Environment Setup

1. Copy the environment template:

```bash
cp .env.example .env
```

2. Update the `.env` file with your configuration:

```env
# Database
DATABASE_URL=postgresql+psycopg2://admin:admin@database:5432/web2

# Authentication
SECRET_KEY=your-secret-key-here
HASH_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CloudFlare R2 (Object Storage)
R2_ACCESS_KEY=your-r2-access-key
R2_SECRET_KEY=your-r2-secret-key
R2_ENDPOINT=https://your-account.r2.cloudflarestorage.com
R2_PUBLIC_URL=https://your-r2-public-url
R2_BUCKET=your-bucket-name

# Email (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASS=your-app-password
MAIL_FROM=noreply@web2.com

# Security Scanning
SNYK_TOKEN=your-snyk-token
SNYK_IMAGE=snyk/snyk:latest

# Storage Paths
SUBMISSIONS_DIR=/app/data/submissions
RESULTS_DIR=/app/data/security_scan_results
DATA_DIR=/app/app/deployment/data
PROJECTS_DIR=/app/app/deployment/data/projects
DEPLOYMENTS_DIR=/app/app/deployment/data/deployments

# LLM Configuration (Optional)
LITAI_API_KEY=your-lightning-ai-key
LITAI_MODEL=your-model-name
LLM_TIMEOUT_SECONDS=30
LLM_MAX_OUTPUT_TOKENS=2000
LLM_MAX_RETRIES=3
LLM_RETRY_BACKOFF=2
LLM_MAX_CONCURRENCY=5

# Docker
BASE_PREVIEW_PORT=3001
PUBLIC_BASE_URL=https://your-domain.com
HOST=your-host
HOST_DATA_DIR=/path/to/host/data
```

## Running the Application

### Using Docker Compose (Recommended)

```bash
# Start all services (database, migration, and API)
docker-compose up -d

# View logs
docker-compose logs -f scanner

# Stop services
docker-compose down

# Rebuild images
docker-compose build --no-cache
docker-compose up -d
```

### Local Development

1. **Install dependencies**:
```bash
pip install -r requirement.txt
```

2. **Run database migrations**:
```bash
alembic upgrade head
```

3. **Seed initial data** (optional):
```bash
python -m app.db.seed
```

4. **Start the server**:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Project Structure

```
web2be/
├── app/
│   ├── main.py                 # FastAPI application entry point
│   ├── core/
│   │   ├── api_router.py      # API routes
│   │   ├── authentication.py  # JWT & auth middleware
│   │   └── plagiarism/        # Plagiarism detection logic
│   ├── models/                # SQLAlchemy ORM models
│   ├── db/
│   │   ├── database.py        # Database connection & session
│   │   ├── schemas.py         # Pydantic schemas
│   │   └── seed.py            # Database seed data
│   ├── deployment/            # Deployment & docker management
│   ├── utils/
│   │   ├── r2.py             # CloudFlare R2 integration
│   │   ├── archive.py        # ZIP handling
│   │   └── email.py          # Email utilities
│   └── deployment/data/       # Runtime data storage
├── alembic/                   # Database migrations
├── docker-compose.yml         # Multi-container configuration
├── Dockerfile                 # Application Docker image
├── requirement.txt            # Python dependencies
├── alembic.ini               # Migration configuration
├── .env.example              # Environment template
└── README.md
```

## API Endpoints

### Health Check
```
GET /
```
Returns API health status.

### File Operations
```
POST /upload-test
```
Upload a file to R2 storage.

```
POST /download-extract-test
```
Download and extract a ZIP file from R2.

```
DELETE /delete-test
```
Delete a directory from submissions.

### Main API Routes
All main API routes are prefixed with `/api` and include:
- User management
- Authentication
- Submissions management
- Plagiarism detection
- Security scanning
- Deployment management

See the API documentation at `/docs` (Swagger UI) or `/redoc` (ReDoc) when the server is running.

## Database

### Migrations

Migrations are managed using Alembic. To create a new migration:

```bash
alembic revision --autogenerate -m "Description of changes"
```

To apply migrations:

```bash
alembic upgrade head
```

## Security Scanning

The application integrates with **Snyk** for security vulnerability scanning:

1. Ensure `SNYK_TOKEN` is set in your `.env` file
2. Scans are triggered during the submission processing pipeline
3. Results are stored in `RESULTS_DIR` and indexed in the database

## Deployment

### Database Service
- **Container**: `web2-database`
- **Image**: `postgres:16`
- **Port**: `5432`
- **Health Check**: Validates PostgreSQL readiness

### Migration Service
- **Container**: `web2-migrate`
- **Task**: Runs Alembic migrations and database seeding
- **Dependency**: Waits for database health check

### API Service (Scanner)
- **Container**: `web2-student-scanner`
- **Port**: `8000`
- **Mount Points**: Submissions, results, and data directories
- **Docker Socket**: Mounted for containerized deployments

## Development

### Running Tests

```bash
robot tests/
```

### Code Quality

The project uses best practices including:
- Type hints throughout
- Async/await for I/O operations
- Comprehensive error handling
- CORS middleware for cross-origin requests
- Trusted host validation

### Logging

Logging is configured via Python's standard logging module. Access logs are available through Docker:

```bash
docker-compose logs scanner
```

### Hot Reload

During development, the API server automatically reloads when code changes:

```bash
uvicorn app.main:app --reload
```

## Support & Documentation

- **API Documentation**: Available at `/docs` (Swagger UI)
- **FastAPI Docs**: https://fastapi.tiangolo.com
- **SQLAlchemy Docs**: https://docs.sqlalchemy.org
- **Snyk Docs**: https://docs.snyk.io

## License

This project is part of the WEB2 educational platform.

## Contributing

When contributing to this project:
1. Create a feature branch
2. Follow PEP 8 style guidelines
3. Add type hints to all functions
4. Update documentation and migrations as needed
5. Test thoroughly before submitting PRs

---

**Last Updated**: 2026-05-29
