#!/usr/bin/env bash
# =============================================================================
#  ARIA — Raspberry Pi 5 Setup Script
#  Run as normal user (not root): bash setup.sh
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"
VOICE_DIR="$SCRIPT_DIR/voices"
SOUND_DIR="$SCRIPT_DIR/sounds"
WW_DIR="$SCRIPT_DIR/wakeword"
DATA_DIR="$SCRIPT_DIR/data"

VOICE_MODEL="en_GB-alan-medium"
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alan/medium"
OWW_MODEL="alexa"
OLLAMA_MODEL="llama3.2:3b"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERR]${NC}  $1"; }

echo ""
echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  ARIA — Raspberry Pi 5 Setup Script  ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
echo ""

# ── System packages ───────────────────────────────────────────────────────────
info "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv \
    portaudio19-dev libasound2-dev \
    sox ffmpeg \
    espeak espeak-ng \
    curl wget git \
    2>/dev/null || warn "Some apt packages may have failed — continuing."
success "System packages installed."

# ── Piper TTS ─────────────────────────────────────────────────────────────────
if ! command -v piper &>/dev/null; then
    info "Installing Piper TTS..."
    PIPER_VERSION="2023.11.14-2"
    PIPER_ARCH="aarch64"  # Raspberry Pi 5 (ARM64)
    PIPER_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_${PIPER_ARCH}.tar.gz"
    TMP_PIPER="/tmp/piper_setup"
    mkdir -p "$TMP_PIPER"
    wget -q --show-progress -O "$TMP_PIPER/piper.tar.gz" "$PIPER_URL"
    tar -xzf "$TMP_PIPER/piper.tar.gz" -C "$TMP_PIPER"
    sudo mv "$TMP_PIPER/piper/piper" /usr/local/bin/piper
    sudo chmod +x /usr/local/bin/piper
    rm -rf "$TMP_PIPER"
    success "Piper TTS installed."
else
    success "Piper TTS already installed."
fi

# ── Voice model ───────────────────────────────────────────────────────────────
mkdir -p "$VOICE_DIR"
ONNX="$VOICE_DIR/${VOICE_MODEL}.onnx"
JSON="$VOICE_DIR/${VOICE_MODEL}.onnx.json"

if [ ! -f "$ONNX" ] || [ ! -f "$JSON" ]; then
    info "Downloading Piper voice: ${VOICE_MODEL}..."
    wget -q --show-progress -O "$ONNX" "${VOICE_BASE}/${VOICE_MODEL}.onnx"
    wget -q --show-progress -O "$JSON" "${VOICE_BASE}/${VOICE_MODEL}.onnx.json"
    success "Voice model downloaded."
else
    success "Voice model already present."
fi

# ── Sound effects (generate with sox) ────────────────────────────────────────
mkdir -p "$SOUND_DIR"
info "Generating sound effects..."

# Wake chime: two-tone ascending beep
sox -n "$SOUND_DIR/wake.wav" \
    synth 0.08 sine 880 \
    synth 0.08 sine 1320 delay 0.08 \
    remix - fade 0.005 0.16 0.02 vol 0.55 2>/dev/null || \
  sox -n "$SOUND_DIR/wake.wav" synth 0.1 sine 1000 vol 0.5

# Done chime: soft descending
sox -n "$SOUND_DIR/done.wav" \
    synth 0.07 sine 660 vol 0.35 2>/dev/null || \
  sox -n "$SOUND_DIR/done.wav" synth 0.05 sine 700 vol 0.3

# Error: low buzz
sox -n "$SOUND_DIR/error.wav" \
    synth 0.15 sine 220 vol 0.4 2>/dev/null || \
  sox -n "$SOUND_DIR/error.wav" synth 0.1 sine 200 vol 0.4

success "Sound effects generated."

# ── Python venv ───────────────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
    info "Creating Python virtual environment..."
    python3 -m venv "$VENV"
fi

info "Installing Python packages..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
success "Python packages installed."

# ── OpenWakeWord model ────────────────────────────────────────────────────────
mkdir -p "$WW_DIR"
info "Pre-downloading OpenWakeWord model: ${OWW_MODEL}..."
"$VENV/bin/python" -c "
from openwakeword.model import Model
try:
    Model(wakeword_models=['${OWW_MODEL}'], inference_framework='onnx')
    print('[OWW] Model ready.')
except Exception as e:
    print(f'[OWW] Warning: {e}')
" || warn "OWW download failed — it will retry on first run."
success "OpenWakeWord ready."

# ── Ollama ────────────────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    success "Ollama installed."
else
    success "Ollama already installed."
fi

# Start Ollama service temporarily to pull model
info "Pulling Ollama model: ${OLLAMA_MODEL} (this may take a few minutes)..."
ollama pull "$OLLAMA_MODEL" || warn "Could not pull model — ensure Ollama service is running."
success "Ollama model ready."

# ── Data dirs ─────────────────────────────────────────────────────────────────
mkdir -p "$DATA_DIR"
success "Data directory created."

# ── Systemd service (auto-start on boot) ──────────────────────────────────────
read -p "Install systemd service (auto-start ARIA on boot)? [y/N] " -r REPLY
if [[ $REPLY =~ ^[Yy]$ ]]; then
    SERVICE_FILE="/etc/systemd/system/aria.service"
    USER_NAME=$(whoami)
    sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=ARIA Voice Assistant
After=network.target sound.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${VENV}/bin/python ${SCRIPT_DIR}/aria.py --headless
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable aria.service
    success "Systemd service installed. ARIA will start on next boot."
    info "To start now: sudo systemctl start aria"
    info "To view logs: journalctl -u aria -f"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ARIA setup complete!              ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit config.json — add your Spotify credentials & HA token"
echo "  2. Run Spotify auth:  source venv/bin/activate && python spotify_setup.py"
echo "  3. Start ARIA:        source venv/bin/activate && python aria.py --headless"
echo "  4. Self-test:         source venv/bin/activate && python aria.py --test"
echo ""
echo "  Wake trigger: say '${OWW_MODEL}' to activate"
echo "  PTT fallback: press Enter in terminal"
echo ""
echo -e "${YELLOW}For a custom 'Hey ARIA' wake word:${NC}"
echo "  Visit https://picovoice.ai → Console → create 'Hey ARIA' .ppn"
echo "  Download it to wakeword/aria.ppn and set 'wake_word_model': 'aria' in config.json"
echo ""
