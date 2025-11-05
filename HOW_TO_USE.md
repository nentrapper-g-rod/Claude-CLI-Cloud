# How To Use Remote Claude CLI Chat

## Understanding The Setup

```
┌─────────────────────────────────────────────────────────────┐
│  THIS MACHINE (192.168.102.16)                              │
│  ┌──────────────────────────────────────────────┐          │
│  │  🖥️  Bridge Server (Port 8765)               │          │
│  │     - Connects to Claude AI                   │          │
│  │     - Manages sessions                        │          │
│  │     - ws://192.168.102.16:8765               │          │
│  └──────────────────────────────────────────────┘          │
│  ┌──────────────────────────────────────────────┐          │
│  │  🌐 Web Server (Port 8888)                    │          │
│  │     - Serves index.html                       │          │
│  │     - http://192.168.102.16:8888             │          │
│  └──────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
                          ↑
                          │ WebSocket + HTTP
                          │
┌─────────────────────────┴───────────────────────────────────┐
│                                                               │
│  OTHER DEVICES (Laptops, Phones, Tablets)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Browser    │  │   Browser    │  │   Browser    │     │
│  │   Chrome     │  │   Firefox    │  │   Safari     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                               │
│  Access: http://192.168.102.16:8888/index.html              │
└───────────────────────────────────────────────────────────────┘
```

## YOU DON'T REGISTER THIS MACHINE

**This machine IS the server.** Other machines register/connect TO it.

Think of it like:
- This machine = Restaurant (provides the service)
- Other devices = Customers (come to the restaurant)

## How To Use (Step by Step)

### Option 1: Use From This Machine

If you have GUI/desktop access on this machine:

1. Open a browser (Chrome, Firefox, etc.)
2. Go to: `http://localhost:8888/index.html`
3. Follow setup steps below

### Option 2: Use From Another Computer (Recommended)

1. **On your laptop/desktop/phone:**
   - Make sure you're on the same WiFi/network as this server
   - Open any web browser

2. **Navigate to the web interface:**
   ```
   http://192.168.102.16:8888/index.html
   ```

3. **First time setup (automatic):**
   - The setup panel will appear
   - You can skip the "Download" section (already done)
   - Scroll down to "Add Machine"

4. **Add this server:**
   - Machine Name: `Local Server` (or any name you like)
   - WebSocket URL: `ws://192.168.102.16:8765`
   - Click "Add Machine"

5. **Close setup:**
   - Click "Close" button
   - You'll see the main interface

6. **Connect to the server:**
   - At the top of the page, you'll see a button: `Local Server`
   - Click it to connect
   - Wait for the dot to turn green 🟢
   - If it stays red 🔴, click again to retry

7. **Start chatting:**
   - Type your message in the text box at the bottom
   - Press Enter (or click Send)
   - Wait for Claude's response

## Understanding "Machines"

The web interface can connect to **multiple machines** at the same time. For example:

```
Your Laptop Browser
    ↓
Can connect to:
    - Work Desktop (ws://192.168.1.50:8765)
    - Home Server (ws://192.168.1.100:8765)
    - Cloud Server (ws://remote.example.com:8765)
    - THIS machine (ws://192.168.102.16:8765)
```

Each "machine" runs its own bridge server, and you add them to the web interface.

## What You've Already Done

✅ Installed the bridge server on THIS machine (192.168.102.16)
✅ Started the bridge server (running on port 8765)
✅ Started the web server (running on port 8888)
✅ Opened firewall ports
✅ Made it accessible on your network

## What You Need To Do Now

Just **use it** from any browser! No registration needed on this machine.

## Quick Access

**Copy this URL and open it on any device:**
```
http://192.168.102.16:8888/index.html
```

**Then add this server in Settings:**
- Name: `Local Server`
- URL: `ws://192.168.102.16:8765`

## Testing The Connection

### Test 1: Check Web Server
```bash
curl http://localhost:8888/index.html
```
Should show HTML content ✅

### Test 2: Check Bridge Server
```bash
netstat -tuln | grep 8765
```
Should show LISTEN ✅

### Test 3: Access From Browser
Open the URL in a browser and add the machine.

## Troubleshooting

**"I can't access the URL from another computer"**
- Check both devices are on same network
- Try: `ping 192.168.102.16` from other device
- Check firewall: `sudo ufw status | grep 8888`

**"The machine button stays red 🔴"**
- Check WebSocket URL is: `ws://192.168.102.16:8765`
- NOT `wss://` (no SSL)
- Click the button again to retry
- Check bridge server is running: `ps aux | grep claude-bridge`

**"I get responses but they're errors"**
- The API key is set to "test-key"
- Get a real key from: https://console.anthropic.com/
- Restart bridge server with real key

## For Multiple Users

Multiple people can use this at the same time:
1. Everyone opens: `http://192.168.102.16:8888/index.html`
2. Everyone adds the same server: `ws://192.168.102.16:8765`
3. Each person has their own independent chat session

## Summary

**What this machine does:** Runs the servers (provides the service)
**What you do:** Open the web page and connect to the servers
**Registration:** Not needed on this machine - it's the destination!

---

**Ready to use!** Just open: http://192.168.102.16:8888/index.html
