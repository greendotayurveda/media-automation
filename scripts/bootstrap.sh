#!/bin/sh
# =============================================================================
# Media Automation Platform — Bootstrap Installer
# =============================================================================
# Usage: sudo ./scripts/bootstrap.sh
# Requires: Ubuntu 22.04+, run as root or with sudo
# =============================================================================

set -e

ROOT="/opt/media-platform"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { printf "${GREEN}[INFO]${NC}  %s\n" "$1"; }
warn()    { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
error()   { printf "${RED}[ERROR]${NC} %s\n" "$1"; exit 1; }
section() { printf "\n${GREEN}═══ %s ═══${NC}\n" "$1"; }

# =============================================================================
# 1. Preflight checks
# =============================================================================
section "Preflight Checks"

# Must run as root
if [ "$(id -u)" -ne 0 ]; then
    error "This script must be run as root: sudo ./scripts/bootstrap.sh"
fi

# Ubuntu check
if ! grep -qi ubuntu /etc/os-release 2>/dev/null; then
    warn "This script is designed for Ubuntu. Proceeding anyway..."
fi

# Docker
if ! command -v docker > /dev/null 2>&1; then
    error "Docker is not installed. Install it first: https://docs.docker.com/engine/install/ubuntu/"
fi
info "Docker: $(docker --version)"

# Docker Compose
if ! docker compose version > /dev/null 2>&1; then
    error "Docker Compose plugin is not installed."
fi
info "Docker Compose: $(docker compose version --short)"

# Git
if ! command -v git > /dev/null 2>&1; then
    warn "Git is not installed. Installing..."
    apt-get install -y git > /dev/null
fi
info "Git: $(git --version)"

# =============================================================================
# 2. Create directory structure
# =============================================================================
section "Creating Directory Structure"

mkdir -p "$ROOT/data/downloads/incoming"
mkdir -p "$ROOT/data/downloads/processing"
mkdir -p "$ROOT/data/downloads/completed"
mkdir -p "$ROOT/data/downloads/failed"

mkdir -p "$ROOT/data/library/movies"
mkdir -p "$ROOT/data/library/malayalam"
mkdir -p "$ROOT/data/library/tamil"
mkdir -p "$ROOT/data/library/bollywood"
mkdir -p "$ROOT/data/library/telugu"
mkdir -p "$ROOT/data/library/kannada"
mkdir -p "$ROOT/data/library/hollywood"
mkdir -p "$ROOT/data/library/other"
mkdir -p "$ROOT/data/library/tvshows"
mkdir -p "$ROOT/data/library/radio"
mkdir -p "$ROOT/data/library/live-tv"
mkdir -p "$ROOT/data/library/recordings"
mkdir -p "$ROOT/data/library/collections"

mkdir -p "$ROOT/data/subtitles"
mkdir -p "$ROOT/data/metadata"
mkdir -p "$ROOT/data/cache"
mkdir -p "$ROOT/data/temp"

mkdir -p "$ROOT/logs"
mkdir -p "$ROOT/backups"

info "Directory structure created at $ROOT"

# =============================================================================
# 3. Set permissions
# =============================================================================
section "Setting Permissions"

# Create media-platform group if not exists
if ! getent group media-platform > /dev/null 2>&1; then
    groupadd media-platform
    info "Created group: media-platform"
fi

chown -R root:media-platform "$ROOT"
chmod -R 775 "$ROOT/data"
chmod -R 755 "$ROOT/logs"
chmod -R 700 "$ROOT/backups"

info "Permissions set"

# =============================================================================
# 4. Setup environment file
# =============================================================================
section "Environment Configuration"

if [ ! -f "$ROOT/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$ROOT/.env"
        warn ".env created from .env.example — EDIT IT NOW before starting services!"
        warn "  nano $ROOT/.env"
    else
        warn ".env.example not found. Create $ROOT/.env manually."
    fi
else
    info ".env already exists — skipping"
fi

# =============================================================================
# 5. Copy config files
# =============================================================================
section "Copying Configuration Files"

if [ -d "$PROJECT_DIR/config" ]; then
    cp -r "$PROJECT_DIR/config" "$ROOT/"
    info "Configuration files copied"
else
    warn "No config/ directory found in $PROJECT_DIR"
fi

if [ -d "$PROJECT_DIR/compose" ]; then
    cp -r "$PROJECT_DIR/compose" "$ROOT/"
    info "Compose files copied"
fi

# =============================================================================
# 6. Docker networks (pre-create)
# =============================================================================
section "Creating Docker Networks"

for NETWORK in mp_frontend mp_backend mp_media mp_monitoring; do
    if ! docker network inspect "$NETWORK" > /dev/null 2>&1; then
        docker network create "$NETWORK"
        info "Created network: $NETWORK"
    else
        info "Network already exists: $NETWORK"
    fi
done

# =============================================================================
# 7. Summary
# =============================================================================
section "Bootstrap Complete"

printf "\n"
info "Platform root:     $ROOT"
info "Docker networks:   mp_frontend, mp_backend, mp_media, mp_monitoring"
printf "\n"
warn "NEXT STEPS:"
printf "  1. Edit the environment file:  nano $ROOT/.env\n"
printf "  2. Start infrastructure:       cd $ROOT && docker compose -f compose/infrastructure.yml up -d\n"
printf "  3. Verify all healthy:         docker compose -f compose/infrastructure.yml ps\n"
printf "\n"
