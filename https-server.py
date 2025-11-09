#!/usr/bin/env python3
"""
HTTPS server for Claude CLI Cloud web interface
"""

import http.server
import ssl
from pathlib import Path

# Server configuration
PORT = 8888
CERT_FILE = Path.home() / '.claude-bridge' / 'server-cert.pem'
KEY_FILE = Path.home() / '.claude-bridge' / 'server-key.pem'

# Create HTTP server
server_address = ('0.0.0.0', PORT)
httpd = http.server.HTTPServer(server_address, http.server.SimpleHTTPRequestHandler)

# Set up SSL context
ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain(CERT_FILE, KEY_FILE)

# Wrap socket with SSL
httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)

print(f"HTTPS Server running on https://0.0.0.0:{PORT}")
print("Press Ctrl+C to stop")

# Serve forever
httpd.serve_forever()
