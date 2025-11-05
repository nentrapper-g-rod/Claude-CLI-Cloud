# Claude CLI Bridge Deployment Guide

## Quick Deploy (One Command)

To install the Claude CLI Bridge on a new server, run this single command:

```bash
curl -fsSL http://100.94.187.56:8889/install | SOURCE_SERVER=http://100.94.187.56:8889 MACHINE_NAME="your-server" WS_PORT=8766 bash
```

This will:
- Download the bridge server
- Install dependencies
- Stop existing service if upgrading
- Set up systemd service with proper logging
- Use specified machine name (or hostname if not set)
- Use port 8766 (enables debug logging automatically)
- Start the bridge server

### Customize Machine Name and Port

You can override the defaults with environment variables:

```bash
curl -fsSL http://100.94.187.56:8889/install | \
  SOURCE_SERVER=http://100.94.187.56:8889 \
  MACHINE_NAME="Production Server" \
  WS_PORT=9000 \
  bash
```

## Interactive Mode

If you download and run the script manually, it will ask for:
1. **Machine Name** - Friendly name for this server (default: hostname)
2. **WebSocket Port** - Port for the bridge (default: 8766)
3. **Confirmation** - Confirm installation settings

## Requirements

The target server needs:
- **Python 3.8+** (check with `python3 --version`)
- **Claude CLI** installed (`claude --version`)
- **Network access** to this deployment server

### Installing Claude CLI

If Claude CLI isn't installed:
```bash
curl -fsSL https://raw.githubusercontent.com/anthropics/claude-cli/main/install.sh | sh
```

## After Installation

Once installed, add the connection in your web terminal:

1. Open the web terminal interface
2. Click **"➕ Add"** in the Connections section
3. Fill in:
   - **Name**: The machine name you chose
   - **Host**: The new server's IP address
   - **Port**: The WebSocket port you chose (default: 8766)
4. Click **Save**
5. Select the connection and start using it!

## Firewall Configuration

Make sure the WebSocket port is open on the new server:

### UFW (Ubuntu/Debian)
```bash
sudo ufw allow 8766/tcp
```

### Firewalld (RHEL/CentOS)
```bash
sudo firewall-cmd --add-port=8766/tcp --permanent
sudo firewall-cmd --reload
```

### iptables
```bash
sudo iptables -A INPUT -p tcp --dport 8766 -j ACCEPT
sudo iptables-save > /etc/iptables/rules.v4
```

## Managing the Service

### Systemd (Linux with systemd)
```bash
# Start
sudo systemctl start claude-bridge

# Stop
sudo systemctl stop claude-bridge

# Status
sudo systemctl status claude-bridge

# Enable on boot
sudo systemctl enable claude-bridge
```

### Viewing Logs

Logs are saved to `~/.claude-bridge/bridge.log` (or `/opt/claude-bridge/bridge.log` for system-wide installs):

```bash
# Follow logs in real-time
tail -f ~/.claude-bridge/bridge.log

# View last 100 lines
tail -100 ~/.claude-bridge/bridge.log

# Filter debug messages (if port 8766)
grep DEBUG ~/.claude-bridge/bridge.log

# Search for errors
grep -i error ~/.claude-bridge/bridge.log
```

### Manual (Without systemd)
```bash
# Start
/opt/claude-bridge/start-bridge.sh

# Or for user install
~/.claude-bridge/start-bridge.sh
```

## Manual Installation

If you prefer to install manually:

1. **Download installer:**
   ```bash
   curl -O http://100.94.187.56:8889/download/install-bridge.sh
   chmod +x install-bridge.sh
   ```

2. **Run installer:**
   ```bash
   SOURCE_SERVER=http://100.94.187.56:8889 ./install-bridge.sh
   ```

## Troubleshooting

### Can't connect to deployment server
- Check the deployment server is running: `ps aux | grep deployment-server`
- Verify port 8889 is open
- Check network connectivity: `curl http://100.94.187.56:8889`

### Bridge won't start
- Check Claude CLI is installed: `claude --version`
- Check Python version: `python3 --version` (need 3.8+)
- Check logs: `tail -f ~/.claude-bridge/bridge.log`
- Check dependencies: `pip3 list | grep websockets`
- Enable debug mode: Use port 8766 or add `--debug` flag manually

### Connection refused from web terminal
- Verify bridge is running: `sudo systemctl status claude-bridge`
- Check port is open: `ss -tlnp | grep 8766`
- Check firewall allows the port
- Verify correct IP and port in connection settings

## Deployment Server Info

**Server:** http://100.94.187.56:8889

**Files Available:**
- `/install` - Quick install script
- `/download/install-bridge.sh` - Installation script
- `/download/claude-bridge-server-terminal.py` - Bridge server

**To view in browser:**
Open http://100.94.187.56:8889 for interactive instructions.

## Stopping the Deployment Server

The deployment server is only needed during installation. You can stop it with:
```bash
ps aux | grep deployment-server | grep -v grep | awk '{print $2}' | xargs kill
```

## Security Notes

- The deployment server serves files over HTTP (not HTTPS)
- Only run it temporarily during deployment
- Consider firewall rules to limit access to trusted networks
- The bridge server itself uses WebSocket (ws://) - consider using a reverse proxy with SSL for production
