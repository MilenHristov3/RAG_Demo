#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# EU Regulation RAG - PostgreSQL + pgvector setup
# Ubuntu / Debian
# PostgreSQL 18
# ============================================================

POSTGRES_VERSION="18"
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="MyPostgres123!"
DATABASE_NAME="eu_rag"

echo " EU Regulation RAG - PostgreSQL Setup"
echo

# 1. Check that script is running on Linux

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "ERROR: This script is intended for Linux."
    exit 1
fi

# 2. Check for sudo

if ! command -v sudo >/dev/null 2>&1; then
    echo "ERROR: sudo is required."
    exit 1
fi

echo "[1/8] Updating package lists..."
sudo apt update

# 3. Install prerequisites

echo "[2/8] Installing PostgreSQL repository prerequisites..."

sudo apt install -y \
    postgresql-common \
    ca-certificates \
    curl

# 4. Configure official PostgreSQL repository

echo "[3/8] Configuring PostgreSQL APT repository..."

sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh

sudo apt update

# 5. Install PostgreSQL 18 + pgvector

echo "[4/8] Installing PostgreSQL ${POSTGRES_VERSION}..."

sudo apt install -y \
    "postgresql-${POSTGRES_VERSION}" \
    "postgresql-client-${POSTGRES_VERSION}" \
    "postgresql-${POSTGRES_VERSION}-pgvector"

# 6. Start and enable PostgreSQL

echo "[5/8] Starting PostgreSQL..."

sudo systemctl enable postgresql
sudo systemctl start postgresql

# Wait briefly for PostgreSQL to become ready
echo "Waiting for PostgreSQL..."

for i in {1..20}; do
    if sudo -u postgres pg_isready >/dev/null 2>&1; then
        break
    fi

    sleep 1
done

if ! sudo -u postgres pg_isready >/dev/null 2>&1; then
    echo "ERROR: PostgreSQL did not become ready."
    exit 1
fi

echo "PostgreSQL is ready."

# 7. Set postgres password and create database

echo "[6/8] Configuring PostgreSQL user..."

sudo -u postgres psql \
    -v ON_ERROR_STOP=1 \
    --dbname=postgres \
    --command="ALTER USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}';"

echo "[7/8] Creating database '${DATABASE_NAME}'..."

sudo -u postgres psql \
    -v ON_ERROR_STOP=1 \
    --dbname=postgres \
    --command="SELECT 'CREATE DATABASE ${DATABASE_NAME}' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DATABASE_NAME}')\gexec"

# 8. Enable pgvector in the project database

echo "[8/8] Enabling pgvector..."

sudo -u postgres psql \
    -v ON_ERROR_STOP=1 \
    --dbname="${DATABASE_NAME}" \
    --command="CREATE EXTENSION IF NOT EXISTS vector;"

echo
echo " Setup completed successfully!"
echo

echo "PostgreSQL:"
sudo -u postgres psql --dbname="${DATABASE_NAME}" --command="SELECT version();"

echo
echo "pgvector:"
sudo -u postgres psql \
    --dbname="${DATABASE_NAME}" \
    --command="SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"

echo
echo "Database:"
echo "  Host:     localhost"
echo "  Port:     5432"
echo "  Database: ${DATABASE_NAME}"
echo "  User:     ${POSTGRES_USER}"
echo "  Password: ${POSTGRES_PASSWORD}"

echo
echo " PostgreSQL + pgvector are ready."