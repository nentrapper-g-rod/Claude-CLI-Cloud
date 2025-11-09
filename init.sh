#!/bin/bash
# v2.6 – MCP config removed (handled by install script)

# Download personal preferences (fast)
mkdir -p ~/.claude-bridge
curl -s http://100.94.187.56:8888/personalpref.txt > ~/.claude-bridge/personalpref.txt 2>/dev/null

# Update Claude settings.json with personal preferences (fast)
if [ -f ~/.claude-bridge/personalpref.txt ]; then
    PREFS=$(cat ~/.claude-bridge/personalpref.txt)

    python3 <<EOF 2>/dev/null
import json
import os

settings_file = os.path.expanduser('~/.claude/settings.json')

# Read existing settings
if os.path.exists(settings_file):
    with open(settings_file, 'r') as f:
        settings = json.load(f)
else:
    settings = {}

# Add or update appendSystemPrompt
settings['appendSystemPrompt'] = '''$PREFS'''

# Write back to file
with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)
EOF
fi

# Run slow operations in background (non-blocking)
(
    # Set Claude UI preferences (only if not already set)
    if [ ! -f ~/.claude-bridge/.prefs-configured ]; then
        claude preferences set editor.theme dark >/dev/null 2>&1 || true
        claude preferences set editor.tabSize 4 >/dev/null 2>&1 || true
        claude preferences set editor.animations false >/dev/null 2>&1 || true
        touch ~/.claude-bridge/.prefs-configured
    fi
) &

echo "✓ Init script v2.6 completed"
