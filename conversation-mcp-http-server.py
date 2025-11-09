#!/usr/bin/env python3
"""
HTTP/SSE MCP Server for Conversation History
Wraps the stdio MCP server to make it accessible over network
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from aiohttp import web
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to the stdio MCP server
MCP_SERVER_PATH = Path(__file__).parent / "conversation-mcp-server.py"

class MCPHttpServer:
    def __init__(self):
        self.process = None
        self.reader = None
        self.writer = None

    async def start_mcp_process(self):
        """Start the stdio MCP server process"""
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(MCP_SERVER_PATH),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        self.reader = self.process.stdout
        self.writer = self.process.stdin
        logger.info("MCP stdio process started")

    async def send_jsonrpc(self, method: str, params: dict = None) -> dict:
        """Send a JSON-RPC request to the MCP server"""
        if not self.writer:
            await self.start_mcp_process()

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {}
        }

        request_line = json.dumps(request) + "\n"
        self.writer.write(request_line.encode())
        await self.writer.drain()

        # Read response
        response_line = await self.reader.readline()
        if not response_line:
            raise Exception("MCP server closed connection")

        return json.loads(response_line)

    async def handle_sse(self, request):
        """Handle Server-Sent Events connection from Claude CLI"""
        response = web.StreamResponse()
        response.headers['Content-Type'] = 'text/event-stream'
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Connection'] = 'keep-alive'
        response.headers['Access-Control-Allow-Origin'] = '*'
        await response.prepare(request)

        try:
            # Send initial endpoint event (required by MCP SSE spec)
            # Format: event: endpoint\ndata: /message\n\n
            await response.write(b"event: endpoint\ndata: /message\n\n")

            # Keep connection alive
            while True:
                await asyncio.sleep(30)
                await response.write(b': keepalive\n\n')
        except asyncio.CancelledError:
            logger.info("SSE connection closed by client")
        except Exception as e:
            logger.error(f"SSE error: {e}")
        finally:
            try:
                await response.write_eof()
            except:
                pass

        return response

    async def handle_message(self, request):
        """Handle MCP message from Claude CLI"""
        try:
            data = await request.json()
            method = data.get('method')
            params = data.get('params', {})

            # Forward to stdio MCP server
            response = await self.send_jsonrpc(method, params)

            return web.json_response(response)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return web.json_response({
                "jsonrpc": "2.0",
                "id": data.get('id'),
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }, status=500)

    async def handle_health(self, request):
        """Health check endpoint"""
        return web.json_response({"status": "ok"})


async def create_app():
    """Create the aiohttp application"""
    server = MCPHttpServer()
    app = web.Application()

    app.router.add_get('/sse', server.handle_sse)
    app.router.add_post('/message', server.handle_message)
    app.router.add_get('/health', server.handle_health)

    return app


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='MCP HTTP Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8767, help='Port to bind to')
    args = parser.parse_args()

    logger.info(f"Starting MCP HTTP server on {args.host}:{args.port}")

    app = asyncio.run(create_app())
    web.run_app(app, host=args.host, port=args.port)
