#!/bin/bash
set -e

# Configuration
SERVICE_NAME="weather-exporter"
INSTALL_DIR="/opt/weather-exporter"
USER_NAME="pi" # Default pi user, change if needed
VENV_DIR="$INSTALL_DIR/venv"

# Ensure we are running as root
if [ "$EUID" -ne 0 ]; then 
  echo "Please run as root"
  exit 1
fi

echo "Installing system dependencies..."
apt-get update
apt-get install -y rtl-433 python3-venv python3-pip

echo "Setting up installation directory at $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp exporter.py requirements.txt "$INSTALL_DIR/"

# Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "Creating systemd service..."
cat > /etc/systemd/system/$SERVICE_NAME.service << EOF
[Unit]
Description=RTL_433 Weather Exporter
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/exporter.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service
systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME

echo "Setup complete! Service $SERVICE_NAME is running."
echo "Check status with: systemctl status $SERVICE_NAME"
