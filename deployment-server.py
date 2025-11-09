#!/usr/bin/env python3
"""
Simple HTTP server to serve Claude Bridge deployment files
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import sys
import re

def get_bridge_version():
    """Read VERSION from claude-bridge-server-terminal.py"""
    try:
        with open('claude-bridge-server-terminal.py', 'r') as f:
            content = f.read()
            match = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"Error reading version: {e}")
    return "unknown"

# Files to serve
SERVED_FILES = {
    '/download/claude-bridge-server-terminal.py': 'claude-bridge-server-terminal.py',
    '/download/install-bridge.sh': 'install-bridge.sh',
    '/download/conversation-mcp-server.py': 'conversation-mcp-server.py',
    '/download/conversation_db.py': 'conversation_db.py',
    '/download/conversation-hook.py': 'conversation-hook.py',
    '/download/install-mcp-config.sh': 'install-mcp-config.sh',
    '/download/check-remote-sync.sh': 'check-remote-sync.sh',
    '/download/claude-with-connection-name.sh': 'claude-with-connection-name.sh',
    '/install': 'install-bridge.sh',  # Shortcut URL
}

class DeploymentHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        # Handle HEAD requests - send headers only, no body
        if self.path in SERVED_FILES:
            filename = SERVED_FILES[self.path]
            filepath = os.path.join(os.path.dirname(__file__), filename)

            if os.path.exists(filepath):
                self.send_response(200)

                # Set content type
                if filename.endswith('.py'):
                    self.send_header('Content-Type', 'text/x-python')
                elif filename.endswith('.sh'):
                    self.send_header('Content-Type', 'text/x-shellscript')
                else:
                    self.send_header('Content-Type', 'application/octet-stream')

                # Get file size for Content-Length
                file_size = os.path.getsize(filepath)
                self.send_header('Content-Length', str(file_size))
                self.end_headers()
                return
            else:
                self.send_error(404, f"File not found: {filename}")
                return
        elif self.path == '/' or self.path == '':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            return
        else:
            self.send_error(404, "Not Found")

    def do_GET(self):
        # Check if requesting a served file
        if self.path in SERVED_FILES:
            filename = SERVED_FILES[self.path]
            filepath = os.path.join(os.path.dirname(__file__), filename)

            if os.path.exists(filepath):
                self.send_response(200)

                # Set content type
                if filename.endswith('.py'):
                    self.send_header('Content-Type', 'text/x-python')
                elif filename.endswith('.sh'):
                    self.send_header('Content-Type', 'text/x-shellscript')
                else:
                    self.send_header('Content-Type', 'application/octet-stream')

                # Read and send file
                with open(filepath, 'rb') as f:
                    content = f.read()
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)

                print(f"Served: {filename} ({len(content)} bytes)")
                return
            else:
                self.send_error(404, f"File not found: {filename}")
                return

        # Root path - show instructions
        elif self.path == '/' or self.path == '':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()

            version = get_bridge_version()

            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Claude Bridge Deployment</title>
                <style>
                    body {{
                        font-family: monospace;
                        max-width: 800px;
                        margin: 50px auto;
                        padding: 20px;
                        background: #1a1a1a;
                        color: #e0e0e0;
                    }}
                    .command {{
                        background: #2d2d2d;
                        padding: 15px;
                        border-radius: 5px;
                        margin: 20px 0;
                        overflow-x: auto;
                    }}
                    .command code {{
                        color: #4a9eff;
                    }}
                    h1 {{ color: #4a9eff; }}
                    h2 {{ color: #3a8eef; }}
                    a {{ color: #4a9eff; }}
                    .version {{
                        display: inline-block;
                        background: #2d2d2d;
                        padding: 5px 10px;
                        border-radius: 3px;
                        margin-left: 10px;
                        font-size: 0.8em;
                        color: #4a9eff;
                    }}
                </style>
            </head>
            <body>
                <h1>🚀 Claude CLI Bridge Deployment <span class="version">v{version}</span></h1>

                <h2>Quick Install (One Command)</h2>
                <p>Run this command on your target server:</p>
                <div class="command">
                    <code>curl -fsSL http://{self.headers.get('Host', 'SERVER_IP')}/install | SOURCE_SERVER=http://{self.headers.get('Host', 'SERVER_IP')} bash</code>
                </div>

                <h2>Manual Install</h2>
                <p>1. Download installer:</p>
                <div class="command">
                    <code>curl -O http://{self.headers.get('Host', 'SERVER_IP')}/download/install-bridge.sh</code>
                </div>

                <p>2. Run installer:</p>
                <div class="command">
                    <code>chmod +x install-bridge.sh<br>
                    SOURCE_SERVER=http://{self.headers.get('Host', 'SERVER_IP')} ./install-bridge.sh</code>
                </div>

                <h2>Available Downloads</h2>
                <ul>
                    <li><a href="/download/install-bridge.sh">install-bridge.sh</a> - Installation script</li>
                    <li><a href="/download/claude-bridge-server-terminal.py">claude-bridge-server-terminal.py</a> - Bridge server</li>
                </ul>

                <h2>What This Does</h2>
                <ul>
                    <li>Downloads the bridge server to your machine</li>
                    <li>Installs Python dependencies (websockets, aiofiles)</li>
                    <li>Creates a systemd service (if available)</li>
                    <li>Configures machine name and port</li>
                    <li>Starts the bridge server</li>
                </ul>

                <h2>New Features</h2>
                <ul>
                    <li>🔄 <strong>Remote Restart</strong> - Restart bridge server from web UI</li>
                    <li>⬆️ <strong>Remote Update</strong> - Pull latest code and restart via web UI</li>
                    <li>🗑️ <strong>Session Filtering</strong> - Invalid sessions automatically hidden</li>
                    <li>⚙️ <strong>Connection Settings</strong> - Manage connections from sidebar</li>
                </ul>

                <h2>Requirements</h2>
                <ul>
                    <li>Python 3.8+</li>
                    <li>Claude CLI installed</li>
                    <li>Git installed (for remote updates)</li>
                    <li>Network access to this server</li>
                </ul>
            </body>
            </html>
            """

            self.wfile.write(html.encode())
            return

        else:
            self.send_error(404, "Not Found")

    def log_message(self, format, *args):
        # Custom log format
        print(f"[{self.log_date_time_string()}] {format % args}")

def main():
    port = 8890

    # Check if files exist
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    required_files = ['claude-bridge-server-terminal.py', 'install-bridge.sh']
    for filename in required_files:
        if not os.path.exists(filename):
            print(f"Error: Required file not found: {filename}")
            sys.exit(1)

    print("=" * 60)
    print("  Claude Bridge Deployment Server")
    print("=" * 60)
    print(f"  Serving from: {script_dir}")
    print(f"  Listening on: http://0.0.0.0:{port}")
    print("=" * 60)
    print("")
    print("Quick Install Command:")
    print(f"  curl -fsSL http://YOUR_SERVER_IP:{port}/install | SOURCE_SERVER=http://YOUR_SERVER_IP:{port} bash")
    print("")
    print("Open in browser for detailed instructions:")
    print(f"  http://YOUR_SERVER_IP:{port}")
    print("")
    print("Press Ctrl+C to stop")
    print("")

    server = HTTPServer(('0.0.0.0', port), DeploymentHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()

if __name__ == '__main__':
    main()
