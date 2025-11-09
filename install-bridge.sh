#!/bin/bash
#
# Claude CLI Bridge Installer
# Downloads and installs the Claude CLI Terminal Bridge Server
#

set -e

echo "================================================"
echo "  Claude CLI Terminal Bridge Installer"
echo "================================================"
echo ""

# Configuration
INSTALL_DIR="/opt/claude-bridge"
SERVICE_USER="${USER}"
DEFAULT_PORT="8766"

# Check if running as root for system-wide install
if [ "$EUID" -eq 0 ]; then
    echo "Running as root - installing system-wide..."
    INSTALL_DIR="/opt/claude-bridge"
    SERVICE_USER="claude-bridge"
else
    echo "Running as user - installing to home directory..."
    INSTALL_DIR="$HOME/.claude-bridge"
    SERVICE_USER="${USER}"
fi

# Check if running interactively
if [ -t 0 ] && [ -z "$MACHINE_NAME" ] && [ -z "$WS_PORT" ]; then
    # Interactive mode - prompt for inputs
    read -p "Enter a name for this machine (e.g., 'production-server'): " INPUT_MACHINE_NAME
    MACHINE_NAME=${INPUT_MACHINE_NAME:-$(hostname)}

    read -p "Enter WebSocket port [${DEFAULT_PORT}]: " INPUT_WS_PORT
    WS_PORT=${INPUT_WS_PORT:-${DEFAULT_PORT}}

    echo ""
    echo "Configuration:"
    echo "  Install Directory: ${INSTALL_DIR}"
    echo "  Machine Name: ${MACHINE_NAME}"
    echo "  WebSocket Port: ${WS_PORT}"
    echo "  Service User: ${SERVICE_USER}"
    echo ""
    read -p "Continue with installation? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi
else
    # Non-interactive mode (piped from curl) or env vars provided - use defaults/env vars
    MACHINE_NAME=${MACHINE_NAME:-$(hostname)}
    WS_PORT=${WS_PORT:-${DEFAULT_PORT}}

    echo "Non-interactive installation mode"
    echo "Configuration:"
    echo "  Install Directory: ${INSTALL_DIR}"
    echo "  Machine Name: ${MACHINE_NAME}"
    echo "  WebSocket Port: ${WS_PORT}"
    echo "  Service User: ${SERVICE_USER}"
    echo ""
    echo "Proceeding with installation..."
fi

# Create install directory
echo "Creating installation directory..."
mkdir -p "${INSTALL_DIR}"

# Download bridge server
echo "Downloading bridge server..."
cd "${INSTALL_DIR}"

# Check if SOURCE_SERVER is set, otherwise prompt
if [ -z "$SOURCE_SERVER" ]; then
    read -p "Enter source server URL (e.g., http://192.168.1.100:8888): " SOURCE_SERVER
fi

curl -f -o claude-bridge-server-terminal.py "${SOURCE_SERVER}/download/claude-bridge-server-terminal.py" || {
    echo "Error: Failed to download bridge server from ${SOURCE_SERVER}"
    echo "Make sure the source server is running and accessible."
    exit 1
}

chmod +x claude-bridge-server-terminal.py

# Download MCP server and dependencies
echo "Downloading MCP server components..."
curl -f -o conversation-mcp-server.py "${SOURCE_SERVER}/download/conversation-mcp-server.py" 2>/dev/null || {
    echo "Warning: Failed to download MCP server (optional)"
}
curl -f -o conversation_db.py "${SOURCE_SERVER}/download/conversation_db.py" 2>/dev/null || {
    echo "Warning: Failed to download conversation DB (optional)"
}
curl -f -o conversation-hook.py "${SOURCE_SERVER}/download/conversation-hook.py" 2>/dev/null || {
    echo "Warning: Failed to download conversation hook (optional)"
}
curl -f -o install-mcp-config.sh "${SOURCE_SERVER}/download/install-mcp-config.sh" 2>/dev/null || {
    echo "Warning: Failed to download MCP config script (optional)"
}

chmod +x conversation-mcp-server.py conversation-hook.py install-mcp-config.sh 2>/dev/null

# Service will be restarted at the end of installation

# Check Python version
echo "Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    echo "Please install Python 3.8 or higher:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "  RHEL/CentOS: sudo yum install python3 python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Found Python ${PYTHON_VERSION}"

# Install Python dependencies (including MCP)
echo "Installing Python dependencies..."
pip3 install --user websockets aiofiles psutil aiohttp mcp 2>/dev/null || \
pip3 install --break-system-packages websockets aiofiles psutil aiohttp mcp 2>/dev/null || \
sudo pip3 install --break-system-packages websockets aiofiles psutil aiohttp mcp 2>/dev/null || {
    echo "Error: Failed to install Python dependencies."
    echo "Please install manually:"
    echo "  pip3 install --break-system-packages websockets aiofiles psutil aiohttp mcp"
    echo "or"
    echo "  sudo apt install python3-websockets python3-aiofiles python3-psutil python3-aiohttp"
    echo "  pip3 install --break-system-packages mcp"
    exit 1
}

# Check if tmux is installed
echo "Checking tmux installation..."
if ! command -v tmux &> /dev/null; then
    echo "Warning: tmux is not installed"
    echo "Install it with:"
    echo "  Ubuntu/Debian: sudo apt install tmux"
    echo "  RHEL/CentOS: sudo yum install tmux"

    if [ -t 0 ]; then
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "Continuing anyway (non-interactive mode)..."
    fi
fi

# Check if Claude CLI is installed
echo "Checking Claude CLI installation..."
if ! command -v claude &> /dev/null; then
    echo "Warning: Claude CLI is not installed"
    echo "Install it with: curl -fsSL https://raw.githubusercontent.com/anthropics/claude-cli/main/install.sh | sh"

    if [ -t 0 ]; then
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "Continuing anyway (non-interactive mode)..."
    fi
fi

# Create systemd service
if command -v systemctl &> /dev/null; then
    echo "Creating systemd service..."

    SERVICE_FILE="/etc/systemd/system/claude-bridge.service"

    # Determine if debug mode should be enabled (port 8766 only)
    DEBUG_FLAG=""
    if [ "${WS_PORT}" = "8766" ]; then
        DEBUG_FLAG=" --debug"
        echo "  Debug mode: ENABLED (port 8766)"
    fi

    # Detect user's home directory for PATH
    if [ "$EUID" -eq 0 ]; then
        USER_HOME=$(eval echo ~${SERVICE_USER})
    else
        USER_HOME="${HOME}"
    fi

    # Create service file with sudo
    sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=Claude CLI Terminal Bridge Server
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${USER_HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/usr/bin/python3 -u ${INSTALL_DIR}/claude-bridge-server-terminal.py --machine-name "${MACHINE_NAME}" --port ${WS_PORT}${DEBUG_FLAG}
Restart=always
RestartSec=3
StandardOutput=append:${INSTALL_DIR}/bridge.log
StandardError=append:${INSTALL_DIR}/bridge.log

[Install]
WantedBy=multi-user.target
EOF

    echo "Reloading systemd..."
    sudo systemctl daemon-reload

    echo ""
    echo "Service installed! You can now:"
    echo "  Start:   sudo systemctl start claude-bridge"
    echo "  Stop:    sudo systemctl stop claude-bridge"
    echo "  Status:  sudo systemctl status claude-bridge"
    echo "  Enable:  sudo systemctl enable claude-bridge  (start on boot)"
    echo ""
else
    echo "Systemd not available. Creating start script..."

    cat > "${INSTALL_DIR}/start-bridge.sh" <<EOF
#!/bin/bash
cd "${INSTALL_DIR}"
python3 claude-bridge-server-terminal.py --machine-name "${MACHINE_NAME}" --port ${WS_PORT}
EOF

    chmod +x "${INSTALL_DIR}/start-bridge.sh"

    echo ""
    echo "Start script created at: ${INSTALL_DIR}/start-bridge.sh"
    echo "Run it with: ${INSTALL_DIR}/start-bridge.sh"
fi

# Configure MCP if files were downloaded
if [ -f "${INSTALL_DIR}/conversation-mcp-server.py" ]; then
    echo ""
    echo "Configuring MCP server..."
    mkdir -p ~/.config/claude

    cat > ~/.config/claude/mcp_config.json <<EOF
{
  "mcpServers": {
    "conversation-history": {
      "command": "python3",
      "args": [
        "${INSTALL_DIR}/conversation-mcp-server.py"
      ],
      "env": {}
    }
  }
}
EOF
    echo "✓ MCP configuration created at ~/.config/claude/mcp_config.json"
fi

# Configure conversation hooks if files were downloaded
if [ -f "${INSTALL_DIR}/conversation-hook.py" ]; then
    echo ""
    echo "Configuring conversation hooks..."
    mkdir -p ~/.claude

    python3 <<PYEOF
import json
from pathlib import Path

settings_file = Path.home() / '.claude' / 'settings.json'

# Read existing settings or create new
if settings_file.exists():
    with open(settings_file, 'r') as f:
        try:
            settings = json.load(f)
        except json.JSONDecodeError:
            settings = {}
else:
    settings = {}

# Configure hooks
hook_path = "${INSTALL_DIR}/conversation-hook.py"
settings['hooks'] = {
    "UserPromptSubmit": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": hook_path
                }
            ]
        }
    ],
    "Stop": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": hook_path
                }
            ]
        }
    ]
}

# Preserve appendSystemPrompt if it exists
if 'appendSystemPrompt' not in settings:
    settings['appendSystemPrompt'] = ""

# Write back
with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print("✓ Conversation hooks configured in ~/.claude/settings.json")
PYEOF
fi

echo ""
echo "================================================"
echo "  Installation Complete!"
echo "================================================"
echo ""
echo "Bridge server installed at: ${INSTALL_DIR}"
echo "Machine name: ${MACHINE_NAME}"
echo "WebSocket port: ${WS_PORT}"
echo ""
echo "To connect from the web interface:"
echo "  1. Open your browser to the web terminal"
echo "  2. Click 'Add Connection'"
echo "  3. Name: ${MACHINE_NAME}"
echo "  4. Host: $(hostname -I | awk '{print $1}')"
echo "  5. Port: ${WS_PORT}"
echo ""
echo "Make sure firewall allows port ${WS_PORT}:"
echo "  UFW:      sudo ufw allow ${WS_PORT}/tcp"
echo "  Firewalld: sudo firewall-cmd --add-port=${WS_PORT}/tcp --permanent"
echo ""

# Restart the service at the end
if command -v systemctl &> /dev/null; then
    echo "Restarting claude-bridge service..."
    sudo systemctl restart claude-bridge 2>&1
    RESTART_EXIT=$?

    if [ $RESTART_EXIT -eq 0 ]; then
        echo "✓ Service restarted successfully!"
        sleep 2
        sudo systemctl status claude-bridge --no-pager || true
    else
        echo "✗ Service restart failed. Check: sudo systemctl status claude-bridge"
    fi
fi
