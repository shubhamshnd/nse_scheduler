#!/usr/bin/env bash
# setup.sh — Raspberry Pi / Linux setup for Nifty Pipeline
# Usage: bash setup.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_NAME="nifty_pipeline"
PYTHON_BIN="$VENV_DIR/bin/python"

echo ""
echo "======================================================"
echo "  Nifty Pipeline — Raspberry Pi Setup"
echo "======================================================"
echo ""
echo "Project dir: $PROJECT_DIR"

# ── 1. System deps ──────────────────────────────────────
echo ""
echo "[1/5] Checking system dependencies..."
if command -v apt-get &>/dev/null; then
    echo "      Detected apt — installing python3-venv if needed..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3-venv python3-pip
fi

PYVER=$(python3 --version 2>&1)
echo "[OK]  $PYVER"

# ── 2. Virtual environment ──────────────────────────────
echo ""
echo "[2/5] Setting up virtual environment..."
if [ -d "$VENV_DIR" ]; then
    echo "      venv/ already exists, skipping creation."
else
    python3 -m venv "$VENV_DIR"
    echo "[OK]  venv created at $VENV_DIR"
fi

# ── 3. Install requirements ─────────────────────────────
echo ""
echo "[3/5] Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
echo "[OK]  Dependencies installed."

# ── 4. Create directories ───────────────────────────────
echo ""
echo "[4/5] Creating data/ and logs/ directories..."
mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs"
echo "[OK]  Directories ready."

# ── 5. Systemd service (optional) ──────────────────────
echo ""
echo "[5/5] Installing systemd service (optional)..."
SERVICE_FILE="$PROJECT_DIR/${SERVICE_NAME}.service"
SYSTEMD_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

# Patch the service file to use the venv python
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Nifty Pipeline Trading Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN $PROJECT_DIR/app.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
echo "      Service file written: $SERVICE_FILE"

read -r -p "      Install as systemd service now? [y/N]: " REPLY
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    sudo cp "$SERVICE_FILE" "$SYSTEMD_PATH"
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl start  "$SERVICE_NAME"
    echo "[OK]  Service enabled and started."
    echo "      Status: sudo systemctl status $SERVICE_NAME"
    echo "      Logs:   sudo journalctl -u $SERVICE_NAME -f"
else
    echo "      Skipped. To install later:"
    echo "        sudo cp $SERVICE_FILE $SYSTEMD_PATH"
    echo "        sudo systemctl enable --now $SERVICE_NAME"
fi

# ── Done ────────────────────────────────────────────────
echo ""
echo "======================================================"
echo "  Setup complete!"
echo "======================================================"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Edit config.yaml — fill in your API keys:"
echo "       alpha_vantage, newsdata_io, groq, telegram_bot, telegram_chat"
echo ""
echo "  2. Start the web server:"
echo "       source venv/bin/activate"
echo "       python app.py"
echo ""
echo "  3. Open browser on your LAN:"
PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR_PI_IP")
echo "       http://$PI_IP:5000"
echo ""
echo "  4. CLI pipeline:"
echo "       python run.py --list-tasks"
echo "       python run.py screen"
echo ""
