#!/usr/bin/env python3
"""
Remote Claude CLI Bridge Server (Proxy Mode)
Version: 2.0
Purpose: WebSocket server that proxies to existing Claude Code servers
"""

import asyncio
import websockets
import json
import os
import sys
import argparse
import httpx
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import traceback

try:
    import aiofiles
except ImportError:
    print("ERROR: Required dependencies not installed.")
    print("Please install: pip install aiofiles websockets httpx")
    sys.exit(1)


class ClaudeBridgeProxyServer:
    """WebSocket server that proxies to Claude Code servers"""

    def __init__(self, machine_name: str, claude_home: str, claude_server_url: str):
        self.machine_name = machine_name
        self.claude_home = Path(claude_home).expanduser()
        self.claude_server_url = claude_server_url.rstrip('/')
        self.clients = set()
        self.session_cache = {}

        print(f"Proxy mode: Will forward requests to {self.claude_server_url}")

    async def handle_client(self, websocket):
        """Handle WebSocket client connection"""
        self.clients.add(websocket)
        client_id = id(websocket)
        print(f"[{datetime.now().isoformat()}] Client {client_id} connected")

        try:
            # Send connection confirmation
            await self.send_message(websocket, {
                "type": "connected",
                "machine": self.machine_name,
                "mode": "proxy",
                "server": self.claude_server_url,
                "timestamp": datetime.now().isoformat()
            })

            # Handle incoming messages
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.route_message(websocket, data)
                except json.JSONDecodeError as e:
                    await self.send_error(websocket, f"Invalid JSON: {e}")
                except Exception as e:
                    await self.send_error(websocket, f"Error processing message: {e}")
                    traceback.print_exc()

        except websockets.exceptions.ConnectionClosed:
            print(f"[{datetime.now().isoformat()}] Client {client_id} disconnected")
        finally:
            self.clients.remove(websocket)

    async def route_message(self, websocket, data: Dict):
        """Route incoming messages to appropriate handlers"""
        msg_type = data.get('type')

        if msg_type == 'discover_sessions':
            await self.handle_discover_sessions(websocket)
        elif msg_type == 'load_session':
            await self.handle_load_session(websocket, data)
        elif msg_type == 'get_projects':
            await self.handle_get_projects(websocket)
        elif msg_type == 'chat':
            await self.handle_chat(websocket, data)
        elif msg_type == 'upload_file':
            await self.handle_upload_file(websocket, data)
        else:
            await self.send_error(websocket, f"Unknown message type: {msg_type}")

    async def handle_discover_sessions(self, websocket):
        """Discover and organize all Claude CLI sessions"""
        print(f"[{datetime.now().isoformat()}] Discovering sessions...")

        try:
            sessions_data = await self.discover_sessions()
            await self.send_message(websocket, {
                "type": "sessions",
                "data": sessions_data,
                "timestamp": datetime.now().isoformat()
            })
            print(f"[{datetime.now().isoformat()}] Sent {len(sessions_data.get('projects', {}))} projects, "
                  f"{len(sessions_data.get('ungrouped', []))} ungrouped sessions")
        except Exception as e:
            await self.send_error(websocket, f"Error discovering sessions: {e}")
            traceback.print_exc()

    async def discover_sessions(self) -> Dict:
        """Scan Claude CLI directories and organize sessions"""
        projects_data = {}
        ungrouped_sessions = []
        session_metadata = {}

        # Parse history.jsonl to get session metadata
        history_file = self.claude_home / "history.jsonl"
        if history_file.exists():
            async with aiofiles.open(history_file, 'r') as f:
                async for line in f:
                    try:
                        entry = json.loads(line.strip())
                        session_id = entry.get('sessionId')
                        if session_id:
                            if session_id not in session_metadata:
                                session_metadata[session_id] = {
                                    'project': entry.get('project'),
                                    'cwd': entry.get('cwd'),
                                    'first_seen': entry.get('timestamp'),
                                    'last_seen': entry.get('timestamp'),
                                    'message_count': 0
                                }
                            else:
                                session_metadata[session_id]['last_seen'] = entry.get('timestamp')
                            session_metadata[session_id]['message_count'] += 1
                    except (json.JSONDecodeError, KeyError):
                        continue

        # Scan projects directory for session files
        projects_dir = self.claude_home / "projects"
        if projects_dir.exists():
            for project_dir in projects_dir.iterdir():
                if not project_dir.is_dir():
                    continue

                project_name = project_dir.name
                sessions_in_project = []

                for session_file in project_dir.glob("*.jsonl"):
                    session_id = session_file.stem

                    # Get metadata from cache or file
                    metadata = session_metadata.get(session_id, {})

                    # Get preview from session file
                    preview = await self.get_session_preview(session_file)

                    # Get last modified time
                    last_modified = datetime.fromtimestamp(session_file.stat().st_mtime).isoformat()

                    session_info = {
                        'session_id': session_id,
                        'last_modified': metadata.get('last_seen') or last_modified,
                        'preview': preview,
                        'message_count': metadata.get('message_count', 0),
                        'cwd': metadata.get('cwd', ''),
                    }

                    sessions_in_project.append(session_info)

                # Group sessions by directory within project
                if sessions_in_project:
                    directories = {}
                    for session in sessions_in_project:
                        cwd = session.get('cwd', 'unknown')
                        if cwd not in directories:
                            directories[cwd] = []
                        directories[cwd].append(session)

                    projects_data[project_name] = {
                        'directories': directories
                    }

        # Sort sessions by last_modified (most recent first)
        for project in projects_data.values():
            for directory in project['directories'].values():
                directory.sort(key=lambda x: x['last_modified'], reverse=True)

        ungrouped_sessions.sort(key=lambda x: x['last_modified'], reverse=True)

        return {
            'projects': projects_data,
            'ungrouped': ungrouped_sessions
        }

    async def get_session_preview(self, session_file: Path) -> str:
        """Extract preview text from session file (first user message)"""
        try:
            async with aiofiles.open(session_file, 'r') as f:
                async for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get('type') == 'user' and entry.get('message'):
                            content = entry['message'].get('content', '')
                            if isinstance(content, str):
                                return content[:100] + ('...' if len(content) > 100 else '')
                            elif isinstance(content, list):
                                # Handle multi-part content
                                for item in content:
                                    if isinstance(item, dict) and item.get('type') == 'text':
                                        text = item.get('text', '')
                                        return text[:100] + ('...' if len(text) > 100 else '')
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass
        return "No preview available"

    async def handle_load_session(self, websocket, data: Dict):
        """Load complete session history from JSONL file"""
        session_id = data.get('session_id')
        if not session_id:
            await self.send_error(websocket, "session_id required")
            return

        print(f"[{datetime.now().isoformat()}] Loading session: {session_id}")

        try:
            # Find session file in projects
            session_file = None
            projects_dir = self.claude_home / "projects"

            for project_dir in projects_dir.glob("*"):
                if project_dir.is_dir():
                    candidate = project_dir / f"{session_id}.jsonl"
                    if candidate.exists():
                        session_file = candidate
                        break

            if not session_file:
                await self.send_error(websocket, f"Session {session_id} not found")
                return

            # Parse session history
            history = []
            async with aiofiles.open(session_file, 'r') as f:
                async for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get('type') in ['user', 'assistant']:
                            history.append({
                                'type': entry['type'],
                                'message': entry.get('message', {}),
                                'timestamp': entry.get('timestamp', ''),
                            })
                    except (json.JSONDecodeError, KeyError):
                        continue

            # Cache the session
            self.session_cache[session_id] = {
                'messages': history,
                'file': str(session_file)
            }

            await self.send_message(websocket, {
                'type': 'session_loaded',
                'session_id': session_id,
                'history': history,
                'timestamp': datetime.now().isoformat()
            })
            print(f"[{datetime.now().isoformat()}] Loaded session with {len(history)} messages")

        except Exception as e:
            await self.send_error(websocket, f"Error loading session: {e}")
            traceback.print_exc()

    async def handle_get_projects(self, websocket):
        """List available Claude CLI projects"""
        try:
            projects = []
            projects_dir = self.claude_home / "projects"

            if projects_dir.exists():
                for project_dir in projects_dir.iterdir():
                    if project_dir.is_dir():
                        projects.append(project_dir.name)

            await self.send_message(websocket, {
                'type': 'projects',
                'data': sorted(projects),
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            await self.send_error(websocket, f"Error getting projects: {e}")

    async def handle_chat(self, websocket, data: Dict):
        """Handle chat message and proxy to Claude Code server"""
        message = data.get('message')
        session_id = data.get('session_id')
        project = data.get('project')
        directory = data.get('directory')
        files = data.get('files', [])

        if not message and not files:
            await self.send_error(websocket, "message or files required")
            return

        print(f"[{datetime.now().isoformat()}] Chat message in session {session_id or 'new'}")
        print(f"[{datetime.now().isoformat()}] Proxying to Claude Code server: {self.claude_server_url}")

        try:
            # Build conversation context
            messages = []

            # Load existing session context if provided
            if session_id and session_id in self.session_cache:
                cached = self.session_cache[session_id]['messages']
                for msg in cached:
                    messages.append(msg['message'])

            # Build user message content
            user_content = []

            if message:
                user_content.append({
                    'type': 'text',
                    'text': message
                })

            # Add file attachments if any
            for file_data in files:
                user_content.append({
                    'type': 'text',
                    'text': f"\n\nFile: {file_data['filename']}\n```\n{file_data['content']}\n```"
                })

            # Add new user message
            messages.append({
                'role': 'user',
                'content': user_content if len(user_content) > 1 else message
            })

            # Proxy to Claude Code server
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Send request to Claude Code server's API
                response = await client.post(
                    f"{self.claude_server_url}/api/chat",
                    json={
                        'messages': messages,
                        'session_id': session_id,
                        'project': project,
                        'directory': directory
                    }
                )

                if response.status_code == 200:
                    result = response.json()

                    # Extract response text and tool uses
                    response_text = result.get('message', '')
                    tool_uses = result.get('tool_uses', [])

                    # Send tool use notifications
                    for tool in tool_uses:
                        await self.send_message(websocket, {
                            'type': 'tool_use',
                            'tool_name': tool.get('name'),
                            'tool_input': tool.get('input', {}),
                            'session_id': session_id,
                            'timestamp': datetime.now().isoformat()
                        })

                    # Send final complete response
                    await self.send_message(websocket, {
                        'type': 'response',
                        'message': response_text,
                        'tool_uses': tool_uses,
                        'session_id': session_id,
                        'timestamp': datetime.now().isoformat()
                    })

                    print(f"[{datetime.now().isoformat()}] Response sent ({len(response_text)} chars, {len(tool_uses)} tools)")
                else:
                    error_msg = f"Claude Code server returned {response.status_code}: {response.text}"
                    await self.send_error(websocket, error_msg)
                    print(f"[{datetime.now().isoformat()}] ERROR: {error_msg}")

        except httpx.ConnectError:
            await self.send_error(websocket, f"Cannot connect to Claude Code server at {self.claude_server_url}")
        except Exception as e:
            await self.send_error(websocket, f"Error in chat: {e}")
            traceback.print_exc()

    async def handle_upload_file(self, websocket, data: Dict):
        """Handle file upload for chat context"""
        filename = data.get('filename')
        content = data.get('content')
        file_type = data.get('file_type', 'text/plain')

        if not filename or not content:
            await self.send_error(websocket, "filename and content required")
            return

        print(f"[{datetime.now().isoformat()}] File uploaded: {filename}")

        # Send confirmation
        await self.send_message(websocket, {
            'type': 'file_uploaded',
            'filename': filename,
            'size': len(content),
            'timestamp': datetime.now().isoformat()
        })

    async def send_message(self, websocket, data: Dict):
        """Send JSON message to websocket"""
        try:
            await websocket.send(json.dumps(data))
        except Exception as e:
            print(f"Error sending message: {e}")

    async def send_error(self, websocket, error_msg: str):
        """Send error message to websocket"""
        await self.send_message(websocket, {
            'type': 'error',
            'message': error_msg,
            'timestamp': datetime.now().isoformat()
        })

    async def start(self, host: str, port: int):
        """Start the WebSocket server"""
        print(f"Starting Claude Bridge Server (Proxy Mode)")
        print(f"Machine: {self.machine_name}")
        print(f"Claude Home: {self.claude_home}")
        print(f"Claude Code Server: {self.claude_server_url}")
        print(f"Listening on: ws://{host}:{port}")
        print(f"Press Ctrl+C to stop\n")

        async with websockets.serve(self.handle_client, host, port):
            await asyncio.Future()  # Run forever


def main():
    parser = argparse.ArgumentParser(
        description='Remote Claude CLI Bridge Server (Proxy Mode)',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8765, help='Port to listen on (default: 8765)')
    parser.add_argument('--machine-name', required=True, help='Name identifier for this machine')
    parser.add_argument('--claude-home', default='~/.claude', help='Claude CLI home directory (default: ~/.claude)')
    parser.add_argument('--claude-server', required=True, help='Claude Code server URL (e.g., http://100.94.187.56:4000)')

    args = parser.parse_args()

    try:
        server = ClaudeBridgeProxyServer(
            machine_name=args.machine_name,
            claude_home=args.claude_home,
            claude_server_url=args.claude_server
        )

        asyncio.run(server.start(args.host, args.port))

    except KeyboardInterrupt:
        print("\n\nShutting down gracefully...")
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
