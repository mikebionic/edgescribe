#!/usr/bin/env bash
#
# setup.sh - One-command installation for edgescribe
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo ""
echo "=================================================="
echo "  edgescribe: setup"
echo "  Private, local, offline audio transcription"
echo "=================================================="
echo ""

# --- Python ---
info "Checking Python..."
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    fail "Python 3.9+ not found. Install it and try again."
fi

PY_VER=$($PY --version 2>&1 | awk '{print $2}')
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
[ "$PY_MINOR" -lt 9 ] && fail "Python $PY_VER is too old. Need 3.9+"
ok "Python $PY_VER"

# --- ffmpeg ---
info "Checking ffmpeg..."
if command -v ffmpeg &>/dev/null; then
    ok "ffmpeg found"
else
    warn "ffmpeg not found. Install: sudo apt install ffmpeg (Linux) / brew install ffmpeg (macOS)"
    warn "Some audio formats won't work without ffmpeg"
fi

# --- RAM ---
info "Checking RAM..."
if command -v free &>/dev/null; then
    RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
    ok "RAM: ${RAM_MB} MB"
    [ "$RAM_MB" -lt 8000 ] && warn "Less than 8 GB RAM - consider using 'medium' model instead of 'large-v3-turbo'"
fi

# --- venv ---
VENV=".venv"
info "Creating virtual environment..."
if [ -d "$VENV" ]; then
    warn "$VENV already exists - skipping"
else
    $PY -m venv "$VENV"
    ok "Virtual environment created"
fi

PIP="$VENV/bin/pip"

info "Installing dependencies..."
$PIP install --upgrade pip --quiet
$PIP install -r requirements.txt --quiet 2>&1 | tail -1
ok "Dependencies installed"

# --- Model preload ---
info "Downloading Whisper model (~1.5 GB, one time only)..."
$VENV/bin/python -c "
from faster_whisper import WhisperModel
model = WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')
print('  Model cached successfully')
"
ok "Whisper model ready"

echo ""
echo "=================================================="
echo -e "  ${GREEN}Setup complete!${NC}"
echo "=================================================="
echo ""
echo "  Quick start:"
echo ""
echo "  # Transcribe a file:"
echo "  $VENV/bin/python transcribe.py --input recording.mp3"
echo ""
echo "  # Launch GUI (browser):"
echo "  $VENV/bin/python gui.py"
echo ""
echo "  # Identify speakers:"
echo "  $VENV/bin/python diarize.py --input recording.mp3 --speakers 2"
echo ""
echo "  All processing is LOCAL. Nothing is sent to the internet."
echo ""
