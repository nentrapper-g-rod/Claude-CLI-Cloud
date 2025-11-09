#!/bin/bash
# Fix Recycle Server Conversation Sync
# Run this on the Recycle server to ensure conversation sync works

echo "=========================================="
echo "  Recycle Server Conversation Sync Fix"
echo "=========================================="
echo ""

# 1. Download latest conversation hook
echo "1. Downloading latest conversation-hook.py..."
curl -fsSL http://100.94.187.56:8890/download/conversation-hook.py -o ~/.claude-bridge/conversation-hook.py
chmod +x ~/.claude-bridge/conversation-hook.py
echo "   ✓ Downloaded"

# 2. Verify it has the correct central server URL
echo "2. Verifying central server URL..."
if grep -q "http://100.94.187.56:8891" ~/.claude-bridge/conversation-hook.py; then
    echo "   ✓ Central server URL is correct (port 8891)"
else
    echo "   ✗ ERROR: Central server URL is wrong!"
    exit 1
fi

# 3. Download conversation_db.py if missing
echo "3. Ensuring conversation_db.py exists..."
if [ ! -f ~/.claude-bridge/conversation_db.py ]; then
    curl -fsSL http://100.94.187.56:8890/download/conversation_db.py -o ~/.claude-bridge/conversation_db.py
    echo "   ✓ Downloaded conversation_db.py"
else
    echo "   ✓ Already exists"
fi

# 4. Configure hooks in .claude.json
echo "4. Configuring hooks in ~/.claude.json..."
python3 <<'PYEOF'
import json
import os
from pathlib import Path

config_file = Path.home() / '.claude.json'

# Read existing config
if config_file.exists():
    with open(config_file, 'r') as f:
        config = json.load(f)
else:
    config = {}

# Set up hooks
hook_path = str(Path.home() / '.claude-bridge' / 'conversation-hook.py')
config['hooks'] = {
    "UserPromptSubmit": {
        "command": "python3",
        "args": [hook_path],
        "input": "stdin"
    },
    "Stop": {
        "command": "python3",
        "args": [hook_path],
        "input": "stdin"
    }
}

# Write back
with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)

print("   ✓ Hooks configured")
PYEOF

# 5. Test connection to central server
echo "5. Testing connection to central server..."
TEST_RESULT=$(curl -s -X POST http://100.94.187.56:8891/api/conversations/sync \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-connection","connection_name":"Recycle Server","project":"/test","cwd":"/test","messages":[]}' 2>&1)

if echo "$TEST_RESULT" | grep -q "success"; then
    echo "   ✓ Central server is reachable and responding"
else
    echo "   ✗ ERROR: Cannot reach central server!"
    echo "   Response: $TEST_RESULT"
    exit 1
fi

# 6. Create a test session to verify hooks work
echo "6. Creating test session to verify hooks..."
echo "   Running: claude --print 'Test from fix script'"
TEST_OUTPUT=$(claude --print "Test sync from Recycle server" 2>&1)

# Wait a moment for hook to process
sleep 2

# Check if debug log was created
if [ -f ~/.claude-bridge/hook-debug.log ]; then
    echo "   ✓ Hook executed (debug log created)"
    echo "   Last hook events:"
    tail -5 ~/.claude-bridge/hook-debug.log | sed 's/^/     /'
else
    echo "   ⚠ Warning: Hook debug log not created"
    echo "   This might be normal for --print mode"
fi

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  • Hooks: Configured in ~/.claude.json"
echo "  • Central Server: http://100.94.187.56:8891"
echo "  • Connection Name: Recycle Server"
echo ""
echo "Next Steps:"
echo "  1. Run an interactive Claude session:"
echo "     claude"
echo ""
echo "  2. Type a test message and exit (Ctrl+D)"
echo ""
echo "  3. Check if hook ran:"
echo "     tail ~/.claude-bridge/hook-debug.log"
echo ""
echo "  4. Verify sync on main server:"
echo "     sqlite3 ~/.claude/conversations.db \"SELECT connection_name, COUNT(*) FROM sessions GROUP BY connection_name;\""
echo ""
