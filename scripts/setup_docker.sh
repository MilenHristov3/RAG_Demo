#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# EU Regulation RAG
# Docker + PostgreSQL 18 + pgvector
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ENV_FILE="${PROJECT_ROOT}/.env"
COMPOSE_FILE="${PROJECT_ROOT}/compose.yaml"
INIT_FILE="${PROJECT_ROOT}/scripts/init.sql"

echo
echo "============================================================"
echo " EU Regulation RAG"
echo " Docker + PostgreSQL + pgvector setup"
echo "============================================================"
echo

# 1. Check .env

echo "[1/8] Checking .env..."

if [[ ! -f "${ENV_FILE}" ]]; then
    echo
    echo "ERROR: .env file was not found."
    echo
    echo "Expected:"
    echo "${ENV_FILE}"
    echo
    echo "Create .env first."
    exit 1
fi

# Load .env
set -a
source "${ENV_FILE}"
set +a

# Check required variables
required_vars=(
    POSTGRES_HOST
    POSTGRES_PORT
    POSTGRES_DB
    POSTGRES_USER
    POSTGRES_PASSWORD
)

for var in "${required_vars[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        echo "ERROR: ${var} is missing from .env"
        exit 1
    fi
done

echo "OK: .env found."

# 2. Check / install Docker

echo
echo "[2/8] Checking Docker..."

if command -v docker >/dev/null 2>&1; then

    echo "Docker is already installed:"
    docker --version

else

    echo "Docker is not installed."
    echo "Installing Docker Engine from the official Docker repository..."

    sudo apt update

    sudo apt install -y \
        ca-certificates \
        curl

    sudo install -m 0755 -d /etc/apt/keyrings

    if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
        sudo curl -fsSL \
            https://download.docker.com/linux/ubuntu/gpg \
            -o /etc/apt/keyrings/docker.asc
    fi

    sudo chmod a+r /etc/apt/keyrings/docker.asc

    UBUNTU_CODENAME="${UBUNTU_CODENAME:-$(. /etc/os-release && echo "${VERSION_CODENAME}")}"
    ARCH="$(dpkg --print-architecture)"

    sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME}
Components: stable
Architectures: ${ARCH}
Signed-By: /etc/apt/keyrings/docker.asc
EOF

    sudo apt update

    sudo apt install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin

    sudo systemctl enable docker
    sudo systemctl start docker

    echo "Docker installed successfully."
fi

# 3. Check Docker daemon

echo
echo "[3/8] Checking Docker daemon..."

if ! sudo systemctl is-active --quiet docker; then
    echo "Docker daemon is not running."
    echo "Starting Docker..."

    sudo systemctl start docker
fi

echo "Docker daemon is running."

# 4. Check Docker Compose

echo
echo "[4/8] Checking Docker Compose..."

if docker compose version >/dev/null 2>&1; then

    echo "Docker Compose is installed:"
    docker compose version

else

    echo "Docker Compose plugin is not installed."
    echo "Installing Docker Compose plugin..."

    sudo apt update
    sudo apt install -y docker-compose-plugin

    echo "Docker Compose installed:"
    docker compose version
fi

# 5. Allow current user to use Docker

echo
echo "[5/8] Checking Docker permissions..."

if docker info >/dev/null 2>&1; then

    echo "Current user can access Docker."

else

    echo "Current user cannot access Docker directly."

    if groups "$USER" | grep -q '\bdocker\b'; then

        echo "User is already in docker group."
        echo "A new login may be required."

        echo
        echo "Please log out/in and run this script again."
        exit 0

    else

        echo "Adding ${USER} to the docker group..."

        sudo usermod -aG docker "$USER"

        echo
        echo "============================================================"
        echo " IMPORTANT"
        echo "============================================================"
        echo
        echo "Your user has been added to the docker group."
        echo
        echo "Please log out and log back in, then run:"
        echo
        echo "    ./scripts/setup_docker.sh"
        echo

        exit 0
    fi
fi

# 6. Prepare compose.yaml

echo
echo "[6/8] Preparing Docker Compose configuration..."

cat > "${COMPOSE_FILE}" <<'EOF'
services:

  postgres:
    image: pgvector/pgvector:pg18

    container_name: eu_rag_postgres

    restart: unless-stopped

    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

    ports:
      - "${POSTGRES_PORT}:5432"

    volumes:
      - postgres_data:/var/lib/postgresql
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql:ro

    healthcheck:
      test:
        [
          "CMD-SHELL",
          "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"
        ]
      interval: 5s
      timeout: 5s
      retries: 20

volumes:

  postgres_data:
EOF

echo "Created:"
echo "${COMPOSE_FILE}"

# 7. Prepare database initialization

echo
echo "[7/8] Preparing PostgreSQL initialization..."

cat > "${INIT_FILE}" <<'EOF'
-- ============================================================
-- EU Regulation RAG
-- PostgreSQL initialization
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;
EOF

echo "Created:"
echo "${INIT_FILE}"

# 8. Start PostgreSQL + pgvector

echo
echo "[8/8] Starting PostgreSQL + pgvector..."

cd "${PROJECT_ROOT}"

docker compose up -d

echo
echo "Waiting for PostgreSQL to become ready..."

for i in {1..30}; do

    if docker compose exec -T postgres \
        pg_isready \
        -U "${POSTGRES_USER}" \
        -d "${POSTGRES_DB}" >/dev/null 2>&1; then

        echo "PostgreSQL is ready."
        break
    fi

    if [[ "$i" -eq 30 ]]; then
        echo
        echo "ERROR: PostgreSQL did not become ready."
        echo
        docker compose logs postgres
        exit 1
    fi

    sleep 2
done

echo
echo "Checking pgvector..."

VECTOR_VERSION=$(
    docker compose exec -T postgres \
    psql \
        -U "${POSTGRES_USER}" \
        -d "${POSTGRES_DB}" \
        -tAc \
        "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
)

if [[ -z "${VECTOR_VERSION}" ]]; then

    echo "ERROR: pgvector extension is not enabled."
    exit 1

fi

echo "pgvector version: ${VECTOR_VERSION}"

echo
echo "============================================================"
echo " Setup completed successfully!"
echo
echo "PostgreSQL:"
echo "  Host:     ${POSTGRES_HOST}"
echo "  Port:     ${POSTGRES_PORT}"
echo "  Database: ${POSTGRES_DB}"
echo "  User:     ${POSTGRES_USER}"
echo
echo "Docker container:"
echo "  ${CONTAINER_NAME:-eu_rag_postgres}"
echo
echo "pgvector:"
echo "  ${VECTOR_VERSION}"
echo
echo "Useful commands:"
echo
echo "  docker compose ps"
echo "  docker compose logs postgres"
echo "  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB}"
echo