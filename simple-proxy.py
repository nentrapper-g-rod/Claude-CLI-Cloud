#!/usr/bin/env python3
"""
Simple HTTP proxy server that forwards /api/* requests to port 8891
and serves static files from current directory for everything else.
"""
import http.server
import socketserver
import urllib.request
import urllib.error
import json
from pathlib import Path

PORT = 8888

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Proxy /api/* requests to port 8891
        if self.path.startswith('/api/'):
            self.proxy_to_settings_api('GET')
        else:
            # Serve static files
            super().do_GET()
    
    def do_POST(self):
        # Proxy /api/* requests to port 8891
        if self.path.startswith('/api/'):
            self.proxy_to_settings_api('POST')
        else:
            self.send_error(404)
    
    def do_OPTIONS(self):
        # Handle CORS preflight
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def proxy_to_settings_api(self, method):
        """Forward request to settings API on port 8891"""
        try:
            target_url = f'http://localhost:8891{self.path}'
            
            # Read request body for POST
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else None
            
            # Create request
            req = urllib.request.Request(target_url, data=body, method=method)
            if body:
                req.add_header('Content-Type', 'application/json')
            
            # Forward request
            with urllib.request.urlopen(req, timeout=10) as response:
                # Send response
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(response.read())
        
        except urllib.error.URLError as e:
            print(f"Proxy error for {self.path}: {e}")
            self.send_error(502, f"Settings API unavailable: {e}")
        except Exception as e:
            print(f"Proxy error for {self.path}: {e}")
            self.send_error(500, str(e))

    def end_headers(self):
        # Add CORS headers to all responses
        if not self.path.startswith('/api/'):
            self.send_header('Access-Control-Allow-Origin', '*')
            # Disable caching for HTML files
            if self.path.endswith('.html') or self.path == '/':
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
        super().end_headers()

if __name__ == '__main__':
    # Allow socket reuse to avoid "Address already in use" errors
    socketserver.TCPServer.allow_reuse_address = True
    # Use ThreadingTCPServer to handle multiple requests concurrently
    with socketserver.ThreadingTCPServer(("", PORT), ProxyHandler) as httpd:
        print(f"Proxy server running on port {PORT} (multi-threaded)")
        print(f"- Static files: http://localhost:{PORT}/")
        print(f"- API proxy: http://localhost:{PORT}/api/* -> http://localhost:8891/api/*")
        httpd.serve_forever()
