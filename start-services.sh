#!/bin/bash
# Claude CLI Cloud Services Startup Script
# Starts conversation API, settings API, and deployment server

echo "Starting Claude CLI Cloud Services..."

# Kill existing processes
pkill -f conversation-api.py
pkill -f settings-api.py
pkill -f deployment-server.py

# Start conversation API (UI service) on port 8889
echo "Starting conversation API on port 8889..."
nohup python3 /opt/Claude-CLI-Cloud/conversation-api.py > /tmp/conversation-api.log 2>&1 &
API_PID=$!

# Start settings API on port 8891
echo "Starting settings API on port 8891..."
nohup python3 /opt/Claude-CLI-Cloud/settings-api.py > /tmp/settings-api.log 2>&1 &
SETTINGS_PID=$!

# Start deployment server on port 8890
echo "Starting deployment server on port 8890..."
nohup python3 /opt/Claude-CLI-Cloud/deployment-server.py > /tmp/deployment-server.log 2>&1 &
DEPLOY_PID=$!

sleep 2

# Check if services are running
if ps -p $API_PID > /dev/null; then
    echo "✓ Conversation API started (PID: $API_PID)"
else
    echo "✗ Conversation API failed to start"
fi

if ps -p $SETTINGS_PID > /dev/null; then
    echo "✓ Settings API started (PID: $SETTINGS_PID)"
else
    echo "✗ Settings API failed to start"
fi

if ps -p $DEPLOY_PID > /dev/null; then
    echo "✓ Deployment server started (PID: $DEPLOY_PID)"
else
    echo "✗ Deployment server failed to start"
fi

echo ""
echo "Services running:"
echo "  Conversation API: http://0.0.0.0:8889"
echo "  Settings API:     http://0.0.0.0:8891"
echo "  Deployment:       http://0.0.0.0:8890"
echo ""
echo "Logs:"
echo "  tail -f /tmp/conversation-api.log"
echo "  tail -f /tmp/settings-api.log"
echo "  tail -f /tmp/deployment-server.log"
