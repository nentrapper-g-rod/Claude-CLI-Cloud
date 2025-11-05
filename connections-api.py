#!/usr/bin/env python3
"""
Simple API server to manage connections data
Runs alongside the main HTTP server
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
from pathlib import Path

CONNECTIONS_FILE = Path(__file__).parent / 'connections.json'
PREFERENCES_FILE = Path(__file__).parent / 'preferences.json'

class ConnectionsHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """Get connections or preferences"""
        if self.path == '/api/connections':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            # Load connections from file
            if CONNECTIONS_FILE.exists():
                with open(CONNECTIONS_FILE, 'r') as f:
                    data = json.load(f)
            else:
                data = []

            self.wfile.write(json.dumps(data).encode())
        elif self.path == '/api/preferences':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            # Load preferences from file
            if PREFERENCES_FILE.exists():
                with open(PREFERENCES_FILE, 'r') as f:
                    data = json.load(f)
            else:
                data = {'personalPreferences': ''}

            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        """Save connections or preferences"""
        if self.path == '/api/connections':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            connections = json.loads(post_data)

            # Save to file
            with open(CONNECTIONS_FILE, 'w') as f:
                json.dump(connections, f, indent=2)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True}).encode())
        elif self.path == '/api/preferences':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            preferences = json.loads(post_data)

            # Save to file
            with open(PREFERENCES_FILE, 'w') as f:
                json.dump(preferences, f, indent=2)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True}).encode())
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        # Suppress log messages
        pass

if __name__ == '__main__':
    port = 8887  # Run on port 8887 (alongside 8888 HTTP server)
    server = HTTPServer(('0.0.0.0', port), ConnectionsHandler)
    print(f"Connections API running on port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
