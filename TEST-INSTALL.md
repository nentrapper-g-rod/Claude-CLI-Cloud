# Install Script Test Instructions

## What Was Fixed

The deployment install script (`install-bridge.sh`) was missing automatic hook configuration. This meant users had to manually configure hooks after installation.

## Changes in v2.11.13

1. **Automatic Hook Configuration**
   - Install script now creates `~/.claude/settings.json`
   - Configures UserPromptSubmit and Stop hooks
   - Points to conversation-hook.py in the install directory

2. **Hostname Auto-Detection**
   - Added mapping for CM Webserver (ip-172-26-13-164)
   - Sessions from different servers are now properly tagged

## Test Steps

To verify the fix works, test on a fresh server:

```bash
# 1. Install bridge server
curl -fsSL http://100.94.187.56:8890/install | \
  SOURCE_SERVER=http://100.94.187.56:8890 \
  MACHINE_NAME="Test Server" \
  WS_PORT=8766 \
  bash

# 2. Verify hooks were configured
cat ~/.claude/settings.json

# Expected output should include:
# {
#   "hooks": {
#     "UserPromptSubmit": [...],
#     "Stop": [...]
#   }
# }

# 3. Start bridge service
sudo systemctl start claude-bridge

# 4. Run a test Claude session
echo "Test installation" | claude --print

# 5. Verify sync to central server
curl -s "http://100.94.187.56:8891/api/conversations/stats" | jq

# Expected: Should see "Test Server" in the stats
```

## What Should Happen

✓ Hooks automatically configured during installation
✓ No manual editing of settings.json required
✓ Conversations sync to central server immediately
✓ Server appears in MCP conversation history

## Rollback if Needed

If there are issues, manually configure hooks:

```bash
python3 <<PYEOF
import json
from pathlib import Path

settings_file = Path.home() / '.claude' / 'settings.json'
settings = json.load(open(settings_file)) if settings_file.exists() else {}

settings['hooks'] = {
    "UserPromptSubmit": [{
        "hooks": [{"type": "command", "command": str(Path.home() / '.claude-bridge' / 'conversation-hook.py')}]
    }],
    "Stop": [{
        "hooks": [{"type": "command", "command": str(Path.home() / '.claude-bridge' / 'conversation-hook.py')}]
    }]
}

json.dump(settings, open(settings_file, 'w'), indent=2)
PYEOF
```
