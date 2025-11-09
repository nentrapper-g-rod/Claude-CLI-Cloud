#!/bin/bash
# Install MCP Server Configuration for Conversation History
# This configures Claude CLI to use the conversation-mcp-server for logging

set -e

echo "=================================================="
echo "  MCP Server Configuration Setup"
echo "=================================================="
echo ""

# Determine installation directory (where bridge is installed)
BRIDGE_DIR="$HOME/.claude-bridge"

# Files needed
MCP_SERVER_SCRIPT="$BRIDGE_DIR/conversation-mcp-server.py"
CONVERSATION_DB_SCRIPT="$BRIDGE_DIR/conversation_db.py"
CONVERSATION_HOOK_SCRIPT="$BRIDGE_DIR/conversation-hook.py"

# Check if files exist
if [ ! -f "$MCP_SERVER_SCRIPT" ]; then
    echo "Error: conversation-mcp-server.py not found in $BRIDGE_DIR"
    echo "Please run the bridge installation first"
    exit 1
fi

if [ ! -f "$CONVERSATION_DB_SCRIPT" ]; then
    echo "Error: conversation_db.py not found in $BRIDGE_DIR"
    exit 1
fi

if [ ! -f "$CONVERSATION_HOOK_SCRIPT" ]; then
    echo "Error: conversation-hook.py not found in $BRIDGE_DIR"
    exit 1
fi

# Make scripts executable
chmod +x "$MCP_SERVER_SCRIPT" "$CONVERSATION_HOOK_SCRIPT"

echo "✓ MCP server scripts found and made executable"
echo ""

# Configure MCP server in Claude CLI
echo "Configuring MCP server in Claude CLI..."

# Remove existing conversation-history server if it exists (to avoid duplicates)
claude mcp remove conversation-history -s user 2>/dev/null || true
claude mcp remove conversation-history -s local 2>/dev/null || true

# Add MCP server using stdio transport
claude mcp add conversation-history python3 "$MCP_SERVER_SCRIPT" --scope user

echo "✓ MCP server configured"
echo ""

# Configure conversation hooks
echo "Configuring conversation hooks..."

CLAUDE_CONFIG="$HOME/.claude.json"

if [ ! -f "$CLAUDE_CONFIG" ]; then
    echo "Error: Claude config not found at $CLAUDE_CONFIG"
    exit 1
fi

# Use Python to update the hooks section in .claude.json
python3 - <<'PYEOF'
import json
import sys
import os

config_path = os.path.expanduser("~/.claude.json")
hook_script = os.path.expanduser("~/.claude-bridge/conversation-hook.py")

try:
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Ensure hooks section exists
    if 'hooks' not in config:
        config['hooks'] = {}

    # Add UserPromptSubmit hook
    config['hooks']['UserPromptSubmit'] = {
        'command': 'python3',
        'args': [hook_script],
        'input': 'stdin'
    }

    # Add Stop hook
    config['hooks']['Stop'] = {
        'command': 'python3',
        'args': [hook_script],
        'input': 'stdin'
    }

    # Write back
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print("✓ Conversation hooks configured")

except Exception as e:
    print(f"Error updating config: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo "Failed to configure hooks"
    exit 1
fi

echo ""
echo "=================================================="
echo "  MCP Setup Complete!"
echo "=================================================="
echo ""
echo "Verifying installation..."
claude mcp list
echo ""
echo "You can now use conversation history MCP tools!"
echo ""
