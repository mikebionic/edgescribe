#!/usr/bin/env bash
#
# deploy.sh — Развёртывание edgescribe на облачном сервере
#
# Поддерживаемые варианты:
#   ./deploy.sh local      — запуск напрямую (venv + systemd)
#   ./deploy.sh docker     — запуск через Docker
#   ./deploy.sh nginx      — настройка Nginx reverse proxy (запустить после local/docker)
#
# Требования:
#   Ubuntu 22.04 LTS (рекомендуется)
#   Python 3.9+, ffmpeg, Docker (опционально)
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
hr()    { echo "────────────────────────────────────────────────────"; }

MODE="${1:-help}"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_USER="${SUDO_USER:-$(whoami)}"
SERVICE_NAME="edgescribe"
VENV="$APP_DIR/.venv"
GUI_HOST="0.0.0.0"
GUI_PORT="7860"
API_PORT="8000"

hr
echo "  edgescribe — Cloud Deployment"
echo "  Mode: $MODE"
echo "  Directory: $APP_DIR"
hr
echo ""

# ─── HELP ─────────────────────────────────────────────────────────────────────
if [ "$MODE" = "help" ]; then
    echo "Usage: ./deploy.sh [mode] [options]"
    echo ""
    echo "Modes:"
    echo "  local      Install venv, download models, create systemd service"
    echo "  docker     Build and run Docker container"
    echo "  nginx      Configure Nginx reverse proxy with SSL (certbot)"
    echo "  status     Show service status"
    echo "  stop       Stop the service"
    echo "  logs       Show live logs"
    echo ""
    echo "Examples:"
    echo "  ./deploy.sh local"
    echo "  ./deploy.sh docker"
    echo "  DOMAIN=transcribe.example.com ./deploy.sh nginx"
    echo "  ./deploy.sh status"
    exit 0
fi

# ─── STATUS ───────────────────────────────────────────────────────────────────
if [ "$MODE" = "status" ]; then
    systemctl status "$SERVICE_NAME" --no-pager 2>/dev/null || echo "Service not installed"
    exit 0
fi

if [ "$MODE" = "stop" ]; then
    systemctl stop "$SERVICE_NAME" 2>/dev/null && ok "Stopped" || warn "Service not running"
    exit 0
fi

if [ "$MODE" = "logs" ]; then
    journalctl -u "$SERVICE_NAME" -f
    exit 0
fi

# ─── LOCAL DEPLOY ─────────────────────────────────────────────────────────────
if [ "$MODE" = "local" ]; then
    info "=== LOCAL DEPLOY ==="
    echo ""

    # Check root for systemd
    [ "$(id -u)" -eq 0 ] || fail "Run with sudo for systemd service: sudo ./deploy.sh local"

    # Check Python
    info "Checking Python..."
    PY=$(command -v python3 || command -v python || true)
    [ -z "$PY" ] && fail "Python 3.9+ not found"
    PY_VER=$($PY --version 2>&1 | awk '{print $2}')
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    [ "$PY_MINOR" -lt 9 ] && fail "Python $PY_VER too old (need 3.9+)"
    ok "Python $PY_VER"

    # Check ffmpeg
    info "Checking ffmpeg..."
    command -v ffmpeg &>/dev/null || {
        info "Installing ffmpeg..."
        apt-get update -qq && apt-get install -y ffmpeg -qq
    }
    ok "ffmpeg ready"

    # RAM check
    info "Checking RAM..."
    RAM_MB=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}' || echo "0")
    ok "RAM: ${RAM_MB} MB"
    [ "$RAM_MB" -lt 12000 ] && warn "Less than 12 GB RAM detected. Recommend 16 GB for large-v3-turbo."

    # Disk check
    info "Checking disk space..."
    FREE_GB=$(df -BG "$APP_DIR" | awk 'NR==2{gsub("G",""); print $4}')
    ok "Free disk: ${FREE_GB} GB"
    [ "${FREE_GB:-0}" -lt 5 ] && warn "Less than 5 GB free. Model requires ~1.5 GB."

    # Create venv
    info "Creating virtual environment..."
    if [ ! -d "$VENV" ]; then
        $PY -m venv "$VENV"
        ok "Virtualenv created: $VENV"
    else
        ok "Virtualenv already exists"
    fi

    "$VENV/bin/pip" install --upgrade pip --quiet
    "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet
    ok "Dependencies installed"

    # Check if API needed
    if grep -q "^fastapi" "$APP_DIR/requirements.txt" 2>/dev/null || [ -f "$APP_DIR/api.py" ]; then
        "$VENV/bin/pip" install fastapi uvicorn --quiet 2>/dev/null || true
    fi

    # Download model
    info "Downloading Whisper model (~1.5 GB, first time only)..."
    "$VENV/bin/python" -c "
from faster_whisper import WhisperModel
model = WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')
print('  Model cached at ~/.cache/huggingface/')
"
    ok "Whisper model ready"

    # Auth password prompt
    AUTH_ARG=""
    echo ""
    read -r -p "Set access password? (leave empty for no auth) user:password  > " AUTH_INPUT
    if [ -n "$AUTH_INPUT" ]; then
        AUTH_ARG="--auth $AUTH_INPUT"
        ok "Auth: enabled ($AUTH_INPUT)"
    else
        warn "Auth: disabled. Consider setting a password for cloud deployment."
    fi

    # Create systemd service (GUI)
    info "Creating systemd service: $SERVICE_NAME-gui..."
    cat > "/etc/systemd/system/${SERVICE_NAME}-gui.service" << EOF
[Unit]
Description=edgescribe GUI
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV/bin/python $APP_DIR/gui.py --host $GUI_HOST --port $GUI_PORT $AUTH_ARG
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # Create systemd service (API)
    if [ -f "$APP_DIR/api.py" ]; then
        info "Creating systemd service: $SERVICE_NAME-api..."
        API_KEY_VAL=""
        read -r -p "Set API key for REST API? (leave empty for no auth) > " API_KEY_VAL
        API_KEY_ENV=""
        [ -n "$API_KEY_VAL" ] && API_KEY_ENV="Environment=EDGESCRIBE_API_KEY=$API_KEY_VAL"

        cat > "/etc/systemd/system/${SERVICE_NAME}-api.service" << EOF
[Unit]
Description=edgescribe REST API
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV/bin/python $APP_DIR/api.py --host $GUI_HOST --port $API_PORT
$API_KEY_ENV
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    fi

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}-gui"
    systemctl start "${SERVICE_NAME}-gui"
    [ -f "/etc/systemd/system/${SERVICE_NAME}-api.service" ] && {
        systemctl enable "${SERVICE_NAME}-api"
        systemctl start "${SERVICE_NAME}-api"
    }

    echo ""
    hr
    ok "Deployment complete!"
    hr
    echo ""
    echo "  GUI:  http://$(hostname -I | awk '{print $1}'):$GUI_PORT"
    [ -f "$APP_DIR/api.py" ] && \
    echo "  API:  http://$(hostname -I | awk '{print $1}'):$API_PORT"
    echo "  Logs: sudo journalctl -u ${SERVICE_NAME}-gui -f"
    echo ""
    echo "  Next step: run  DOMAIN=yourdomain.com sudo ./deploy.sh nginx"
    echo ""
fi

# ─── DOCKER DEPLOY ────────────────────────────────────────────────────────────
if [ "$MODE" = "docker" ]; then
    info "=== DOCKER DEPLOY ==="
    echo ""

    command -v docker &>/dev/null || fail "Docker not installed. Install: curl -fsSL https://get.docker.com | sh"

    # Create Dockerfile if not exists
    if [ ! -f "$APP_DIR/Dockerfile" ]; then
        info "Creating Dockerfile..."
        cat > "$APP_DIR/Dockerfile" << 'DOCKERFILE'
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi uvicorn

COPY transcribe.py diarize.py gui.py api.py ./

# Pre-download model into image (optional: speeds up cold start)
# RUN python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')"

EXPOSE 7860 8000

CMD ["python", "gui.py", "--host", "0.0.0.0", "--port", "7860"]
DOCKERFILE
        ok "Dockerfile created"
    fi

    # Create docker-compose.yml
    if [ ! -f "$APP_DIR/docker-compose.yml" ]; then
        info "Creating docker-compose.yml..."
        cat > "$APP_DIR/docker-compose.yml" << 'COMPOSE'
version: '3.9'

services:
  edgescribe-gui:
    build: .
    container_name: edgescribe-gui
    restart: unless-stopped
    ports:
      - "7860:7860"
    volumes:
      - huggingface_cache:/root/.cache/huggingface   # model cache persists
      - ./transcripts:/app/transcripts               # save transcriptions here
    environment:
      - HF_HUB_OFFLINE=0   # allow model download on first run
    command: python gui.py --host 0.0.0.0 --port 7860

  edgescribe-api:
    build: .
    container_name: edgescribe-api
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - huggingface_cache:/root/.cache/huggingface
    environment:
      - EDGESCRIBE_API_KEY=${EDGESCRIBE_API_KEY:-}
    command: python api.py --host 0.0.0.0 --port 8000

volumes:
  huggingface_cache:
COMPOSE
        ok "docker-compose.yml created"
    fi

    info "Building Docker image..."
    docker compose -f "$APP_DIR/docker-compose.yml" build

    info "Starting containers..."
    docker compose -f "$APP_DIR/docker-compose.yml" up -d

    echo ""
    hr
    ok "Docker deployment complete!"
    hr
    echo ""
    echo "  GUI:  http://$(hostname -I | awk '{print $1}'):7860"
    echo "  API:  http://$(hostname -I | awk '{print $1}'):8000"
    echo "  Logs: docker compose logs -f"
    echo "  Stop: docker compose down"
    echo ""
    echo "  To set API key:  export EDGESCRIBE_API_KEY=mykey && docker compose up -d"
    echo ""
fi

# ─── NGINX + SSL ──────────────────────────────────────────────────────────────
if [ "$MODE" = "nginx" ]; then
    info "=== NGINX + SSL SETUP ==="
    echo ""

    [ "$(id -u)" -eq 0 ] || fail "Run with sudo: sudo DOMAIN=yourdomain.com ./deploy.sh nginx"

    DOMAIN="${DOMAIN:-}"
    [ -z "$DOMAIN" ] && {
        read -r -p "Enter your domain (e.g. transcribe.example.com): " DOMAIN
    }
    [ -z "$DOMAIN" ] && fail "Domain is required"
    ok "Domain: $DOMAIN"

    command -v nginx &>/dev/null || {
        info "Installing nginx..."
        apt-get update -qq && apt-get install -y nginx -qq
    }
    command -v certbot &>/dev/null || {
        info "Installing certbot..."
        apt-get install -y certbot python3-certbot-nginx -qq
    }

    info "Creating nginx config..."
    cat > "/etc/nginx/sites-available/edgescribe" << NGINX
upstream edgescribe_gui {
    server 127.0.0.1:$GUI_PORT;
}
upstream edgescribe_api {
    server 127.0.0.1:$API_PORT;
}

server {
    listen 80;
    server_name $DOMAIN;

    # Large file uploads (audio files can be big)
    client_max_body_size 500M;
    proxy_read_timeout 3600;
    proxy_send_timeout 3600;

    location /api/ {
        proxy_pass http://edgescribe_api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    location / {
        proxy_pass http://edgescribe_gui;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX

    ln -sf /etc/nginx/sites-available/edgescribe /etc/nginx/sites-enabled/
    nginx -t && systemctl reload nginx
    ok "Nginx configured"

    info "Obtaining SSL certificate (Let's Encrypt)..."
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "admin@$DOMAIN" || {
        warn "Certbot failed. Ensure DNS A record for $DOMAIN points to this server."
        warn "Run manually: sudo certbot --nginx -d $DOMAIN"
    }

    echo ""
    hr
    ok "HTTPS setup complete!"
    hr
    echo ""
    echo "  GUI: https://$DOMAIN"
    echo "  API: https://$DOMAIN/api"
    echo "  Docs: https://$DOMAIN/api/docs"
    echo ""
fi
