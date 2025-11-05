# 🟢 Bridge Server Running

## Server Information

**Status:** ✅ Running
**Machine Name:** Local Server
**Host:** 0.0.0.0 (all interfaces)
**Port:** 8765
**WebSocket URL:** `ws://localhost:8765`

**Process ID:** Check with `ps aux | grep claude-bridge`

## How to Access

### Option 1: Open Web Interface Locally

1. Open the file in your browser:
   ```bash
   # If you have a browser on this machine:
   xdg-open /opt/Claude-CLI-Cloud/index.html
   # Or manually open: file:///opt/Claude-CLI-Cloud/index.html
   ```

2. In the web interface:
   - Click "⚙ Settings"
   - Add machine:
     - **Name:** `Local Server`
     - **URL:** `ws://localhost:8765`
   - Click "Add Machine"
   - Click the "Local Server" button in the top bar to connect

### Option 2: Access from Another Computer (Same Network)

1. Find this machine's IP address:
   ```bash
   hostname -I | awk '{print $1}'
   # Or: ip addr show | grep "inet " | grep -v 127.0.0.1
   ```

2. On your other computer:
   - Open `index.html` in browser
   - Add machine with URL: `ws://MACHINE_IP:8765`
   - Replace `MACHINE_IP` with the IP from step 1

### Option 3: Access via Tunneling (Internet Access)

If you want to access from anywhere:

**Using ngrok:**
```bash
# Install ngrok: https://ngrok.com/download
ngrok tcp 8765

# Use the ngrok URL in web interface
# Example: ws://0.tcp.ngrok.io:12345
```

**Using Tailscale (Recommended):**
```bash
# Install tailscale: https://tailscale.com/download
sudo tailscale up

# Get your Tailscale IP
tailscale ip -4

# Use: ws://100.x.y.z:8765
```

## Server Management

### Check Server Status
```bash
# Check if running
ps aux | grep claude-bridge

# Check if port is listening
netstat -tuln | grep 8765

# Check logs (if running in background)
# Look for the process output
```

### Stop Server
```bash
# Find process ID
ps aux | grep claude-bridge | grep -v grep | awk '{print $2}'

# Kill process
kill <PID>

# Or force kill
kill -9 <PID>
```

### Restart Server
```bash
# Stop existing server first
pkill -f claude-bridge-server.py

# Start new instance
cd /opt/Claude-CLI-Cloud
./venv/bin/python3 claude-bridge-server.py --machine-name "Local Server" --port 8765 --api-key "test-key" 2>&1 &
```

### View Real-time Logs
```bash
# If you want to run in foreground with logs visible:
cd /opt/Claude-CLI-Cloud
./venv/bin/python3 claude-bridge-server.py --machine-name "Local Server" --port 8765 --api-key "test-key"

# Press Ctrl+C to stop
```

## Test Connection

### Quick Test with curl
```bash
# This will fail (WebSocket required), but shows server is responding
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: test" http://localhost:8765
```

### Test with Web Interface
1. Open `index.html`
2. Add machine with `ws://localhost:8765`
3. Check for green dot 🟢 next to "Local Server"
4. Type a test message

## Configuration

### Current Configuration

- **API Key Source:** Command line argument (from Claude CLI config)
- **Claude Home:** Default (~/.claude)
- **Virtual Environment:** ./venv (Python packages installed here)

### Custom Configuration

To change settings, stop the server and restart with different arguments:

```bash
# Different port
./venv/bin/python3 claude-bridge-server.py --machine-name "My Server" --port 9000 --api-key "your-key"

# Different Claude home
./venv/bin/python3 claude-bridge-server.py --machine-name "My Server" --claude-home "/custom/path/.claude" --api-key "your-key"

# Bind to specific IP
./venv/bin/python3 claude-bridge-server.py --machine-name "My Server" --host 192.168.1.100 --api-key "your-key"

# Using environment variable for API key
export ANTHROPIC_API_KEY="your-real-key-here"
./venv/bin/python3 claude-bridge-server.py --machine-name "My Server"
```

## Firewall Configuration

If you can't connect from other machines, you may need to open the firewall:

```bash
# Ubuntu/Debian
sudo ufw allow 8765/tcp

# CentOS/RHEL
sudo firewall-cmd --permanent --add-port=8765/tcp
sudo firewall-cmd --reload
```

## Troubleshooting

### Can't Connect from Web Interface

**Check 1:** Is server running?
```bash
ps aux | grep claude-bridge
```

**Check 2:** Is port open?
```bash
netstat -tuln | grep 8765
```

**Check 3:** Firewall blocking?
```bash
sudo ufw status  # Ubuntu/Debian
sudo firewall-cmd --list-all  # CentOS/RHEL
```

**Check 4:** Correct URL?
- Local access: `ws://localhost:8765`
- Network access: `ws://MACHINE_IP:8765`
- NOT `wss://` (that's for SSL)

### Server Crashes or Errors

**Check API Key:**
```bash
# Verify API key is valid
echo $ANTHROPIC_API_KEY
```

**Check Dependencies:**
```bash
./venv/bin/pip list | grep -E "websockets|anthropic|aiofiles"
```

**View Error Output:**
Run server in foreground to see errors:
```bash
./venv/bin/python3 claude-bridge-server.py --machine-name "Local Server"
```

### No Sessions Found

This is normal if:
- Claude CLI not installed
- No previous usage of Claude CLI
- Sessions in non-standard location

**Solution:** Just start chatting! The system will work without existing sessions.

## Next Steps

1. ✅ Server is running
2. 📱 Open web interface (`index.html`)
3. ⚙️ Add this server in Settings
4. 💬 Start chatting with Claude!

See **QUICKSTART.md** for detailed usage instructions.

---

**Server Started:** $(date)
**Location:** /opt/Claude-CLI-Cloud
**Python:** ./venv/bin/python3
