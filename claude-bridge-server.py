#!/usr/bin/env python3
"""
Remote Claude CLI Bridge Server
Version: 1.0
Purpose: WebSocket server that bridges web interface to Claude CLI sessions
"""

import asyncio
import websockets
import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import traceback

try:
    from anthropic import Anthropic
    import aiofiles
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("ERROR: Required dependencies not installed.")
    print("Please install: pip install anthropic aiofiles websockets watchdog")
    sys.exit(1)


class SessionFileWatcher(FileSystemEventHandler):
    """Watch for changes to session JSONL files"""

    def __init__(self, bridge_server, loop):
        self.bridge_server = bridge_server
        self.loop = loop

    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith('.jsonl'):
            return

        # Extract session ID from filename
        session_id = Path(event.src_path).stem
        print(f"[FILE WATCHER] Detected change in session: {session_id}")

        # Notify bridge server of change
        asyncio.run_coroutine_threadsafe(
            self.bridge_server.handle_session_update(session_id, event.src_path),
            self.loop
        )


class ClaudeBridgeServer:
    """WebSocket server that bridges web UI to Claude CLI sessions"""

    def __init__(self, machine_name: str, claude_home: str, api_key: Optional[str] = None):
        self.machine_name = machine_name
        self.claude_home = Path(claude_home).expanduser()

        # Try to get API key from: 1) parameter, 2) env var, 3) Claude CLI config
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')

        if not self.api_key:
            # Try reading from Claude CLI config
            config_file = self.claude_home / "config.json"
            if config_file.exists():
                try:
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                        self.api_key = config.get('api_key')
                except Exception as e:
                    print(f"Warning: Could not read Claude CLI config: {e}")

        if not self.api_key or self.api_key == 'test-key':
            print("WARNING: Using test API key - responses will fail with 401 errors")
            print("Set a real key via: --api-key, ANTHROPIC_API_KEY env var, or ~/.claude/config.json")
            self.api_key = self.api_key or 'test-key'

        self.anthropic = Anthropic(api_key=self.api_key)
        self.clients = set()

        # Session cache: {session_id: {messages: [], metadata: {}}}
        self.session_cache = {}

        # Track which clients are watching which sessions
        # {session_id: set(websockets)}
        self.session_watchers = {}

        # File watcher (will be started in async context)
        self.file_observer = None
        self.file_watcher_loop = None

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
            # Remove from all session watchers
            for session_id, watchers in self.session_watchers.items():
                watchers.discard(websocket)

    async def route_message(self, websocket, data: Dict):
        """Route incoming messages to appropriate handlers"""
        msg_type = data.get('type')

        if msg_type == 'get_config':
            await self.handle_get_config(websocket)
        elif msg_type == 'save_config':
            await self.handle_save_config(websocket, data)
        elif msg_type == 'discover_sessions':
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

    async def handle_get_config(self, websocket):
        """Send server configuration to client"""
        try:
            config_file = Path(__file__).parent / "server-config.json"

            if config_file.exists():
                async with aiofiles.open(config_file, 'r') as f:
                    config_data = json.loads(await f.read())
            else:
                # Default config
                config_data = {
                    "version": "1.0",
                    "machines": [],
                    "settings": {
                        "theme": "dark",
                        "auto_discover_on_connect": True,
                        "show_recent_chats": True,
                        "recent_chats_count": 10
                    },
                    "last_active_machine": None,
                    "last_active_session": None
                }

            await self.send_message(websocket, {
                "type": "config",
                "data": config_data,
                "timestamp": datetime.now().isoformat()
            })
            print(f"[{datetime.now().isoformat()}] Sent configuration to client")

        except Exception as e:
            await self.send_error(websocket, f"Error loading config: {e}")
            traceback.print_exc()

    async def handle_save_config(self, websocket, data: Dict):
        """Save configuration from client"""
        try:
            config_data = data.get('config')
            if not config_data:
                await self.send_error(websocket, "No config data provided")
                return

            config_file = Path(__file__).parent / "server-config.json"

            async with aiofiles.open(config_file, 'w') as f:
                await f.write(json.dumps(config_data, indent=2))

            await self.send_message(websocket, {
                "type": "config_saved",
                "timestamp": datetime.now().isoformat()
            })
            print(f"[{datetime.now().isoformat()}] Configuration saved")

        except Exception as e:
            await self.send_error(websocket, f"Error saving config: {e}")
            traceback.print_exc()

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

            # Register this client as a watcher for real-time updates
            if session_id not in self.session_watchers:
                self.session_watchers[session_id] = set()
            self.session_watchers[session_id].add(websocket)

            await self.send_message(websocket, {
                'type': 'session_loaded',
                'session_id': session_id,
                'history': history,
                'timestamp': datetime.now().isoformat()
            })
            print(f"[{datetime.now().isoformat()}] Loaded session with {len(history)} messages - watching for updates")

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
        """Handle chat message and call Anthropic API"""
        message = data.get('message')
        session_id = data.get('session_id')
        project = data.get('project')
        directory = data.get('directory')
        files = data.get('files', [])  # Support file attachments

        if not message and not files:
            await self.send_error(websocket, "message or files required")
            return

        print(f"[{datetime.now().isoformat()}] Chat message in session {session_id or 'new'}")

        try:
            # Build conversation context
            messages = []

            # Load existing session context if provided
            if session_id and session_id in self.session_cache:
                cached = self.session_cache[session_id]['messages']
                for msg in cached:
                    # Clean message - only keep 'role' and 'content' fields
                    # The Anthropic API rejects any extra fields
                    raw_msg = msg['message']
                    if isinstance(raw_msg, dict) and 'role' in raw_msg and 'content' in raw_msg:
                        clean_msg = {
                            'role': raw_msg['role'],
                            'content': raw_msg['content']
                        }
                        messages.append(clean_msg)

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

            # Call Anthropic API (non-streaming for now to get it working)
            response_text = ""
            tool_uses = []

            # Use synchronous API call (simpler, works reliably)
            response = self.anthropic.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=8096,
                messages=messages
            )

            # Extract response text
            for block in response.content:
                if block.type == 'text':
                    response_text += block.text
                elif block.type == 'tool_use':
                    tool_uses.append({
                        'name': block.name,
                        'input': block.input if hasattr(block, 'input') else {}
                    })

            # Send tool use notifications
            for tool in tool_uses:
                await self.send_message(websocket, {
                    'type': 'tool_use',
                    'tool_name': tool['name'],
                    'tool_input': tool['input'],
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

    def setup_file_watcher(self, loop):
        """Setup file system watcher for session files"""
        try:
            projects_dir = self.claude_home / "projects"
            if projects_dir.exists():
                self.file_watcher_loop = loop
                event_handler = SessionFileWatcher(self, loop)
                self.file_observer = Observer()
                self.file_observer.schedule(event_handler, str(projects_dir), recursive=True)
                self.file_observer.start()
                print(f"✓ File watcher started for: {projects_dir}")
            else:
                print(f"Warning: Projects directory not found: {projects_dir}")
        except Exception as e:
            print(f"Warning: Could not start file watcher: {e}")
            import traceback
            traceback.print_exc()

    async def handle_session_update(self, session_id: str, file_path: str):
        """Handle real-time session file updates"""
        try:
            print(f"[SESSION UPDATE] Session {session_id} changed")
            print(f"[SESSION UPDATE] Watchers: {len(self.session_watchers.get(session_id, set()))} clients")

            # Check if anyone is watching this session
            if session_id not in self.session_watchers or not self.session_watchers[session_id]:
                print(f"[SESSION UPDATE] No watchers for session {session_id}")
                return

            # Read the last few lines from the file
            new_messages = await self.read_new_messages(file_path)

            if new_messages:
                # Notify all clients watching this session
                for websocket in list(self.session_watchers[session_id]):
                    try:
                        await self.send_message(websocket, {
                            'type': 'session_update',
                            'session_id': session_id,
                            'new_messages': new_messages,
                            'timestamp': datetime.now().isoformat()
                        })
                    except:
                        # Remove disconnected clients
                        self.session_watchers[session_id].discard(websocket)

        except Exception as e:
            print(f"Error handling session update: {e}")

    async def read_new_messages(self, file_path: str, count: int = 5) -> List[Dict]:
        """Read the last N messages from a session file"""
        try:
            messages = []
            async with aiofiles.open(file_path, 'r') as f:
                lines = await f.readlines()
                # Get last N lines
                for line in lines[-count:]:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get('type') in ['user', 'assistant']:
                            messages.append({
                                'type': entry['type'],
                                'message': entry.get('message', {}),
                                'timestamp': entry.get('timestamp', ''),
                            })
                    except (json.JSONDecodeError, KeyError):
                        continue
            return messages
        except Exception as e:
            print(f"Error reading messages: {e}")
            return []

    async def start(self, host: str, port: int):
        """Start the WebSocket server"""
        print(f"Starting Claude Bridge Server")
        print(f"Machine: {self.machine_name}")
        print(f"Claude Home: {self.claude_home}")
        print(f"Listening on: ws://{host}:{port}")

        # Start file watcher with current event loop
        loop = asyncio.get_running_loop()
        self.setup_file_watcher(loop)

        print(f"Press Ctrl+C to stop\n")

        async with websockets.serve(self.handle_client, host, port):
            await asyncio.Future()  # Run forever


def main():
    parser = argparse.ArgumentParser(
        description='Remote Claude CLI Bridge Server',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8765, help='Port to listen on (default: 8765)')
    parser.add_argument('--machine-name', required=True, help='Name identifier for this machine')
    parser.add_argument('--claude-home', default='~/.claude', help='Claude CLI home directory (default: ~/.claude)')
    parser.add_argument('--api-key', help='Anthropic API key (or set ANTHROPIC_API_KEY env var)')

    args = parser.parse_args()

    try:
        server = ClaudeBridgeServer(
            machine_name=args.machine_name,
            claude_home=args.claude_home,
            api_key=args.api_key
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
