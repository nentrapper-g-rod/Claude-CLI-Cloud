#!/bin/bash
# Claude CLI Wrapper with Connection Name
# Automatically sets CLAUDE_CONNECTION_NAME based on hostname or custom config

# Try to get machine name from ~/.claude-bridge/config if it exists
if [ -f ~/.claude-bridge/config ]; then
    MACHINE_NAME=$(grep "MACHINE_NAME=" ~/.claude-bridge/config | cut -d= -f2 | tr -d '"')
fi

# If no config, try hostname
if [ -z "$MACHINE_NAME" ]; then
    MACHINE_NAME=$(hostname)
fi

# Set the environment variable for conversation hooks
export CLAUDE_CONNECTION_NAME="$MACHINE_NAME"

# Pass all arguments to claude
exec claude "$@"
