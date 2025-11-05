# 🌐 Web Interface Access Instructions

## ✅ System Status: FULLY OPERATIONAL

Both servers are running and accessible on your network!

### 🔗 Access URL

Open this URL in **ANY web browser** on **ANY computer** on your network:

```
http://192.168.102.16:8888/index.html
```

### 📱 Quick Start (First Time)

1. **Open the URL above** in your browser

2. **Setup will appear automatically** - click through it

3. **Add this server** in Settings:
   - Click "⚙ Settings" button
   - Scroll to "Add Machine" section
   - Fill in:
     - **Machine Name:** `Local Server`
     - **WebSocket URL:** `ws://192.168.102.16:8765`
   - Click "Add Machine"
   - Click "Close"

4. **Connect to the server:**
   - Click the "Local Server" button in the top bar
   - Wait for green dot 🟢 to appear
   - If it stays red, click it again to retry

5. **Start chatting!**
   - Type your message in the text box
   - Press Enter to send
   - Wait for Claude's response

### 🖥️ Server Details

**Web Interface Server (HTTP):**
- Port: 8888
- Serves the web interface (index.html)
- URL: http://192.168.102.16:8888/

**Bridge Server (WebSocket):**
- Port: 8765
- Handles communication with Claude AI
- URL: ws://192.168.102.16:8765

**Firewall:**
- Both ports open and accessible from network
- UFW rules configured

### 💡 Tips

**Multiple Computers:**
- You can access from multiple computers simultaneously
- Each browser maintains its own connection
- Sessions are independent per browser

**Bookmarks:**
- Bookmark the URL for easy access: `http://192.168.102.16:8888/index.html`
- Or save the URL to your desktop

**Mobile Devices:**
- Works on phones and tablets too!
- Connect to same WiFi network
- Open URL in mobile browser

**Session Discovery:**
- If you have Claude CLI installed, existing sessions will appear in the sidebar
- Click "⟳ Refresh Sessions" to rescan

### 🔧 Features

- ✅ Real-time chat with Claude
- ✅ Streaming responses
- ✅ File attachments (click 📎)
- ✅ Session history and discovery
- ✅ Project organization
- ✅ Search and filter
- ✅ Dark theme interface

### 🆘 Troubleshooting

**Can't connect to Local Server (red dot)?**
- Check URL is exactly: `ws://192.168.102.16:8765`
- Note: `ws://` not `wss://`
- Click the red button to retry connection
- Check both computers on same network

**Page won't load?**
- Check URL: `http://192.168.102.16:8888/index.html`
- Make sure both computers on same WiFi/network
- Try refreshing the page (F5)

**Green dot but no response?**
- This is normal - the API key is set to "test-key"
- For actual Claude responses, you need a real Anthropic API key
- Edit the bridge server startup command with real key

### 🔑 Using a Real API Key

To get actual Claude responses, stop and restart the bridge server with your real API key:

```bash
# Stop current server
pkill -f claude-bridge-server.py

# Start with real API key
cd /opt/Claude-CLI-Cloud
export ANTHROPIC_API_KEY="your-real-anthropic-key-here"
./venv/bin/python3 claude-bridge-server.py --machine-name "Local Server"

# Or pass directly:
./venv/bin/python3 claude-bridge-server.py --machine-name "Local Server" --api-key "sk-ant-your-key-here"
```

Get your API key from: https://console.anthropic.com/

### 📊 Server Management

**Check if servers are running:**
```bash
# Bridge server
ps aux | grep claude-bridge

# Web server
ps aux | grep http.server
```

**Stop servers:**
```bash
# Stop bridge server
pkill -f claude-bridge-server.py

# Stop web server
pkill -f "http.server 8888"
```

**Restart servers:**
```bash
cd /opt/Claude-CLI-Cloud

# Start bridge server
./venv/bin/python3 claude-bridge-server.py --machine-name "Local Server" --api-key "your-key" &

# Start web server
nohup python3 -m http.server 8888 &
```

### 🎯 Next Steps

1. **Try it now!** Open: http://192.168.102.16:8888/index.html
2. **Add the server** in Settings
3. **Connect** (look for green dot 🟢)
4. **Get a real API key** for actual responses
5. **Explore features** - file uploads, session history, etc.

---

**Quick Access Link:** http://192.168.102.16:8888/index.html

**System Status:** ✅ Running and ready!
