# Quick Start Guide - Remote Claude CLI Chat

Get up and running in 5 minutes!

## Prerequisites

- Python 3.7+ installed
- Anthropic API key ([Get one here](https://console.anthropic.com/))
- Modern web browser

## Step 1: Install Dependencies (2 minutes)

```bash
cd /opt/Claude-CLI-Cloud
pip3 install anthropic aiofiles websockets
```

## Step 2: Set API Key (30 seconds)

```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

💡 **Tip:** Add this to your `~/.bashrc` or `~/.zshrc` to make it permanent:

```bash
echo 'export ANTHROPIC_API_KEY="your-key-here"' >> ~/.bashrc
source ~/.bashrc
```

## Step 3: Start Bridge Server (30 seconds)

```bash
python3 claude-bridge-server.py --machine-name "My Computer"
```

You should see:
```
Starting Claude Bridge Server
Machine: My Computer
Claude Home: /home/user/.claude
Listening on: ws://0.0.0.0:8765
Press Ctrl+C to stop
```

**Leave this terminal running!**

## Step 4: Open Web Interface (30 seconds)

In your web browser, open:
```
file:///opt/Claude-CLI-Cloud/index.html
```

Or double-click `index.html` in your file manager.

## Step 5: Configure Connection (1 minute)

1. The setup panel will appear automatically
2. Skip the download step (you already have the files)
3. Scroll to "Add Machine" section
4. Fill in:
   - **Machine Name:** `My Computer`
   - **WebSocket URL:** `ws://localhost:8765`
5. Click "Add Machine"
6. Click "Close"

## Step 6: Start Chatting! (30 seconds)

1. Your machine should appear in the top bar with a green dot 🟢
2. If it's not green, click it to connect
3. Type a message and press Enter
4. Wait for Claude's response

🎉 **You're all set!**

## Quick Commands

### Start Server
```bash
python3 claude-bridge-server.py --machine-name "My Computer"
```

### Start Server on Custom Port
```bash
python3 claude-bridge-server.py --machine-name "My Computer" --port 9000
```

### View Help
```bash
python3 claude-bridge-server.py --help
```

## Common Issues & Fixes

### ❌ "ModuleNotFoundError: No module named 'websockets'"

**Fix:**
```bash
pip3 install websockets anthropic aiofiles
```

### ❌ "ValueError: API key required"

**Fix:**
```bash
export ANTHROPIC_API_KEY="your-key-here"
# Then restart the bridge server
```

### ❌ "Connection failed" in web interface

**Fixes:**
1. Check bridge server is running (green terminal output)
2. Try clicking the machine button again to reconnect
3. Verify URL is `ws://localhost:8765` (not `wss://`)
4. Check firewall isn't blocking port 8765

### ❌ "No sessions found"

This is normal if:
- You don't have Claude CLI installed
- You haven't used Claude CLI before
- Your sessions are in a non-standard location

**Solution:** Just start chatting! Sessions will be created automatically.

## Using with Multiple Machines

### Remote Machine (e.g., Work Laptop)

1. Install dependencies on the remote machine
2. Start bridge server:
   ```bash
   python3 claude-bridge-server.py --machine-name "Work Laptop"
   ```
3. Find the machine's IP address:
   ```bash
   # Linux
   ip addr show

   # macOS
   ifconfig | grep "inet "
   ```
4. Note the IP (e.g., `192.168.1.100`)

### Your Computer

1. Open `index.html` in browser
2. Click "Settings" button
3. Add machine:
   - **Name:** `Work Laptop`
   - **URL:** `ws://192.168.1.100:8765`
4. Click on "Work Laptop" in top bar to connect

### Over Internet (Using ngrok)

**On remote machine:**
```bash
# Terminal 1: Start bridge server
python3 claude-bridge-server.py --machine-name "Remote Server"

# Terminal 2: Start ngrok tunnel
ngrok tcp 8765
```

Copy the ngrok URL (e.g., `0.tcp.ngrok.io:12345`)

**On your computer:**
1. Open web interface
2. Add machine with URL: `ws://0.tcp.ngrok.io:12345`

## Next Steps

Now that you're up and running:

- ✅ **Try file uploads** - Click "📎 Attach Files" button
- ✅ **Load existing sessions** - Expand projects in sidebar (if you have Claude CLI installed)
- ✅ **Start new sessions** - Click "+ New Session" button
- ✅ **Add more machines** - Connect to multiple computers
- ✅ **Search sessions** - Use search box in sidebar

## Keyboard Shortcuts

- **Enter** - Send message
- **Shift+Enter** - New line in message
- **Ctrl+R** - Refresh sessions (when focused on refresh button)

## Tips for Best Experience

1. **Keep browser tab open** - Connection closes when tab closes
2. **One message at a time** - Wait for response before sending next
3. **File attachments** - Best for text files (code, docs, configs)
4. **Search sessions** - Use preview text to find old conversations
5. **Multiple machines** - Great for home, work, and servers

## Need More Help?

See the full **README.md** for:
- Detailed network configuration
- Security considerations
- Message protocol documentation
- Troubleshooting guide
- Advanced usage

---

**Happy chatting with Claude! 🤖💬**
