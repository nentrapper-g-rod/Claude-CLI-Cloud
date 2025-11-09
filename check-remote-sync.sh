#!/bin/bash
# Check if this conversation is synced to central server
# Run this on any bridge server (Recycle, CM Webserver, etc.)

echo "========================================"
echo "  Check Remote Sync Status"
echo "========================================"
echo ""

# Get the current session ID from environment or latest session
if [ -n "$CLAUDE_SESSION_ID" ]; then
    SESSION_ID="$CLAUDE_SESSION_ID"
    echo "Using current session ID: $SESSION_ID"
else
    # Get most recent session from local DB
    SESSION_ID=$(sqlite3 ~/.claude/conversations.db "SELECT session_id FROM sessions ORDER BY last_modified DESC LIMIT 1;" 2>/dev/null)
    if [ -z "$SESSION_ID" ]; then
        echo "✗ No sessions found in local database"
        exit 1
    fi
    echo "Using most recent session ID: $SESSION_ID"
fi

echo ""

# Check local database
echo "1. Local Database:"
LOCAL_DATA=$(sqlite3 ~/.claude/conversations.db "SELECT s.connection_name, COUNT(m.id) as msg_count FROM sessions s LEFT JOIN messages m ON s.session_id = m.session_id WHERE s.session_id = '$SESSION_ID' GROUP BY s.session_id;" 2>/dev/null)

if [ -n "$LOCAL_DATA" ]; then
    LOCAL_CONN=$(echo "$LOCAL_DATA" | cut -d'|' -f1)
    LOCAL_MSG=$(echo "$LOCAL_DATA" | cut -d'|' -f2)
    echo "   Connection: $LOCAL_CONN"
    echo "   Messages: $LOCAL_MSG"
else
    echo "   ✗ Session not found locally"
fi

echo ""

# Query central server
echo "2. Central Server (100.94.187.56:8891):"
REMOTE_DATA=$(curl -s "http://100.94.187.56:8891/api/conversations/query?session_id=$SESSION_ID")

if echo "$REMOTE_DATA" | grep -q '"found":true'; then
    echo "   ✓ Session found in central database!"
    echo "$REMOTE_DATA" | jq '.'
else
    echo "   ✗ Session NOT found in central database"
    echo "$REMOTE_DATA" | jq '.'
fi

echo ""
echo "========================================"
echo ""

# Show overall stats
echo "Overall Statistics from Central Server:"
curl -s "http://100.94.187.56:8891/api/conversations/stats" | jq '.stats'

echo ""
echo "========================================"
