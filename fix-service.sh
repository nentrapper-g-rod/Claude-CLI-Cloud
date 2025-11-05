#!/bin/bash
# Fix claude-bridge service to log to file instead of journal

SERVICE_FILE="/etc/systemd/system/claude-bridge.service"

if [ ! -f "$SERVICE_FILE" ]; then
    echo "Service file not found: $SERVICE_FILE"
    exit 1
fi

# Get install directory from service file
INSTALL_DIR=$(grep "WorkingDirectory=" "$SERVICE_FILE" | cut -d= -f2)
SERVICE_USER=$(grep "User=" "$SERVICE_FILE" | head -1 | cut -d= -f2)

echo "Fixing service for:"
echo "  Install Dir: $INSTALL_DIR"
echo "  User: $SERVICE_USER"

# Get machine name and port from ExecStart
EXEC_START=$(grep "ExecStart=" "$SERVICE_FILE" | cut -d= -f2-)
MACHINE_NAME=$(echo "$EXEC_START" | grep -oP '(?<=--machine-name ")[^"]+')
WS_PORT=$(echo "$EXEC_START" | grep -oP '(?<=--port )\d+')

echo "  Machine: $MACHINE_NAME"
echo "  Port: $WS_PORT"

# Update service file
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Claude CLI Terminal Bridge Server
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 -u ${INSTALL_DIR}/claude-bridge-server-terminal.py --machine-name "${MACHINE_NAME}" --port ${WS_PORT}
Restart=always
RestartSec=10
StandardOutput=append:${INSTALL_DIR}/bridge.log
StandardError=append:${INSTALL_DIR}/bridge.log

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Restarting service..."
sudo systemctl restart claude-bridge

sleep 2
sudo systemctl status claude-bridge --no-pager

echo ""
echo "Service fixed! Logs are now at: ${INSTALL_DIR}/bridge.log"
echo "View logs with: tail -f ${INSTALL_DIR}/bridge.log"
