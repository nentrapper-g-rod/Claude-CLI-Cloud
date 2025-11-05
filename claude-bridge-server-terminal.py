#!/usr/bin/env python3
"""
Remote Claude CLI Bridge Server (Terminal Mode)
Purpose: WebSocket server that relays between web UI and actual Claude CLI process
"""

VERSION = "1.8.1"

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
import pty
import select
import termios
import struct
import fcntl

try:
    import aiofiles
    import psutil
except ImportError:
    print("ERROR: Required dependencies not installed.")
    print("Please install: pip install aiofiles websockets psutil")
    sys.exit(1)

# Global debug flag
DEBUG_MODE = False

def debug_log(message: str):
    """Print debug messages if debug mode is enabled"""
    if DEBUG_MODE:
        timestamp = datetime.now().isoformat()
        print(f"[DEBUG {timestamp}] {message}", flush=True)


class ClaudeTerminalSession:
    """Manages a PTY session with Claude CLI"""

    def __init__(self, session_id: str, project_dir: str = None, skip_permissions: bool = False, use_resume: bool = False, personal_preferences: str = None):
        self.session_id = session_id
        self.project_dir = project_dir
        self.skip_permissions = skip_permissions
        self.use_resume = use_resume
        self.personal_preferences = personal_preferences
        self.master_fd = None
        self.pid = None
        self.websockets = set()

    async def start(self):
        """Start Claude CLI in a PTY"""
        # Create a pseudo-terminal
        self.pid, self.master_fd = pty.fork()

        if self.pid == 0:
            # Child process - execute Claude CLI
            os.environ['TERM'] = 'xterm-256color'

            # Redirect stderr to avoid debug output bleeding into PTY
            # (but keep stdout for terminal output)
            debug_fd = os.open('/tmp/claude-bridge-debug.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            os.dup2(debug_fd, 2)  # Redirect stderr to debug log
            os.close(debug_fd)

            # Change to the working directory BEFORE building command (if provided)
            if self.project_dir:
                if os.path.isdir(self.project_dir):
                    os.chdir(self.project_dir)

            # Build command args
            if self.use_resume:
                # Use --resume for interactive menu
                args = ['claude', '--resume']
            elif self.session_id:
                # Use --resume with session ID to directly load that session
                args = ['claude', '--resume', self.session_id]
            else:
                # Start fresh session (no session ID)
                args = ['claude']

            if self.skip_permissions:
                args.append('--dangerously-skip-permissions')

            # Add personal preferences as system prompt if provided
            if self.personal_preferences and self.personal_preferences.strip():
                system_prompt = f"Personal preferences to consider:\n\n{self.personal_preferences}"
                args.extend(['--append-system-prompt', system_prompt])

            os.execvp('claude', args)
        else:
            # Parent process - make non-blocking
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            print(f"Started Claude CLI for session {self.session_id} (PID: {self.pid})")

    async def read_output(self):
        """Read output from Claude CLI"""
        try:
            data = os.read(self.master_fd, 4096)
            return data.decode('utf-8', errors='replace')
        except OSError:
            return None

    async def write_input(self, text: str):
        """Write input to Claude CLI"""
        try:
            os.write(self.master_fd, text.encode('utf-8'))
        except OSError as e:
            print(f"Error writing to CLI: {e}")

    def close(self):
        """Close the PTY session"""
        if self.master_fd:
            os.close(self.master_fd)
        if self.pid:
            try:
                os.kill(self.pid, 15)  # SIGTERM
            except:
                pass


class ShellSession:
    """Manages a PTY session with a regular shell"""

    def __init__(self):
        self.session_id = 'shell'
        self.master_fd = None
        self.pid = None
        self.websockets = set()

    async def start(self):
        """Start a bash shell in a PTY"""
        # Create a pseudo-terminal
        self.pid, self.master_fd = pty.fork()

        if self.pid == 0:
            # Child process - execute bash
            os.environ['TERM'] = 'xterm-256color'
            os.environ['PS1'] = r'\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
            os.execvp('bash', ['bash'])
        else:
            # Parent process - make non-blocking
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            print(f"Started shell session (PID: {self.pid})")

    async def read_output(self):
        """Read output from shell"""
        try:
            data = os.read(self.master_fd, 4096)
            return data.decode('utf-8', errors='replace')
        except OSError:
            return None

    async def write_input(self, text: str):
        """Write input to shell"""
        try:
            os.write(self.master_fd, text.encode('utf-8'))
        except OSError as e:
            print(f"Error writing to shell: {e}")

    def close(self):
        """Close the PTY session"""
        if self.master_fd:
            os.close(self.master_fd)
        if self.pid:
            try:
                os.kill(self.pid, 15)  # SIGTERM
            except:
                pass


class ClaudeBridgeTerminalServer:
    """WebSocket server that bridges web UI to Claude CLI terminal"""

    def __init__(self, machine_name: str, claude_home: str):
        self.machine_name = machine_name
        self.claude_home = Path(claude_home).expanduser()
        self.clients = set()
        self.sessions = {}  # session_id -> ClaudeTerminalSession or ShellSession
        self.session_cache = {}
        self.open_tabs = {}  # session_id -> {sessionId, title, projectDir, type}
        self.personal_preferences = ''  # Store synced personal preferences

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
                "mode": "terminal",
                "timestamp": datetime.now().isoformat()
            })

            # Send open tabs to client for restoration
            if self.open_tabs:
                await self.send_message(websocket, {
                    "type": "restore_tabs",
                    "tabs": list(self.open_tabs.values()),
                    "timestamp": datetime.now().isoformat()
                })

            # Handle incoming messages
            async for message in websocket:
                try:
                    debug_log(f"Received message from client {client_id}: {message[:200]}...")
                    data = json.loads(message)
                    debug_log(f"Parsed JSON: {data}")
                    await self.route_message(websocket, data)
                except json.JSONDecodeError as e:
                    error_msg = f"Invalid JSON: {e}"
                    debug_log(f"JSON decode error: {error_msg}")
                    await self.send_error(websocket, error_msg)
                except Exception as e:
                    error_msg = f"Error processing message: {e}"
                    debug_log(f"Message processing error: {error_msg}")
                    await self.send_error(websocket, error_msg)
                    traceback.print_exc()

        except websockets.exceptions.ConnectionClosed:
            print(f"[{datetime.now().isoformat()}] Client {client_id} disconnected")
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error handling client {client_id}: {e}")
            traceback.print_exc()
        finally:
            self.clients.discard(websocket)
            # Clean up any sessions owned by this client
            closed_sessions = []
            for session_id, session in list(self.sessions.items()):
                if websocket in session.websockets:
                    session.websockets.discard(websocket)
                    if len(session.websockets) == 0:
                        print(f"[{datetime.now().isoformat()}] Closing orphaned session: {session_id}")
                        try:
                            session.close()
                        except Exception as e:
                            print(f"[{datetime.now().isoformat()}] Error closing session {session_id}: {e}")
                        del self.sessions[session_id]
                        closed_sessions.append(session_id)

            if closed_sessions:
                print(f"[{datetime.now().isoformat()}] Cleaned up {len(closed_sessions)} session(s): {closed_sessions}")

    async def route_message(self, websocket, data: Dict):
        """Route incoming messages to appropriate handlers"""
        msg_type = data.get('type')

        if msg_type == 'discover_sessions':
            await self.handle_discover_sessions(websocket)
        elif msg_type == 'load_session':
            await self.handle_load_session(websocket, data)
        elif msg_type == 'start_terminal':
            await self.handle_start_terminal(websocket, data)
        elif msg_type == 'start_shell':
            await self.handle_start_shell(websocket, data)
        elif msg_type == 'start_new_session':
            await self.handle_start_new_session(websocket, data)
        elif msg_type == 'close_session':
            await self.handle_close_session(websocket, data)
        elif msg_type == 'reconnect_session':
            await self.handle_reconnect_session(websocket, data)
        elif msg_type == 'upload_file':
            await self.handle_upload_file(websocket, data)
        elif msg_type == 'list_directory':
            await self.handle_list_directory(websocket, data)
        elif msg_type == 'download_file':
            await self.handle_download_file(websocket, data)
        elif msg_type == 'upload_file_to_path':
            await self.handle_upload_file_to_path(websocket, data)
        elif msg_type == 'terminal_input':
            await self.handle_terminal_input(websocket, data)
        elif msg_type == 'get_projects':
            await self.handle_get_projects(websocket)
        elif msg_type == 'restart_server':
            await self.handle_restart_server(websocket)
        elif msg_type == 'update_server':
            await self.handle_update_server(websocket, data)
        elif msg_type == 'get_version':
            await self.handle_get_version(websocket)
        elif msg_type == 'sync_preferences':
            await self.handle_sync_preferences(websocket, data)
        elif msg_type == 'get_metrics':
            await self.handle_get_metrics(websocket)
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
            print(f"[{datetime.now().isoformat()}] Sent {len(sessions_data.get('projects', {}))} projects")
        except Exception as e:
            await self.send_error(websocket, f"Error discovering sessions: {e}")
            traceback.print_exc()

    async def discover_sessions(self) -> Dict:
        """Scan Claude CLI directories and organize sessions"""
        projects_data = {}
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
                    metadata = session_metadata.get(session_id, {})

                    # Validate session file is readable and has valid content
                    is_valid = False
                    message_count = 0
                    session_cwd = None

                    try:
                        async with aiofiles.open(session_file, 'r') as f:
                            line_count = 0
                            async for line in f:
                                line_count += 1
                                try:
                                    entry = json.loads(line.strip())
                                    is_valid = True  # At least one valid JSON line
                                    # Count messages
                                    if entry.get('type') in ['user', 'assistant']:
                                        message_count += 1
                                    # Extract cwd from session data (usually in first few entries)
                                    if not session_cwd and 'cwd' in entry:
                                        session_cwd = entry.get('cwd')
                                except (json.JSONDecodeError, KeyError):
                                    continue

                            # If file is empty or has no valid JSON, skip it
                            if line_count == 0 or not is_valid:
                                print(f"[{datetime.now().isoformat()}] Skipping invalid/empty session file: {session_file}")
                                continue

                    except Exception as e:
                        print(f"[{datetime.now().isoformat()}] Error reading session file {session_file}: {e}")
                        continue  # Skip unreadable session files

                    preview = await self.get_session_preview(session_file)
                    last_modified = datetime.fromtimestamp(session_file.stat().st_mtime).isoformat()

                    # Skip sessions with "Warmup" or "No preview" in the preview
                    if preview:
                        if 'Warmup' in preview:
                            print(f"[{datetime.now().isoformat()}] Skipping Warmup session: {session_id}")
                            continue
                        if 'No preview' in preview or preview == 'No preview available':
                            print(f"[{datetime.now().isoformat()}] Skipping session without preview: {session_id}")
                            continue

                    # Use cwd from session file, fallback to metadata, then unknown
                    cwd = session_cwd or metadata.get('cwd', '') or 'unknown'

                    session_info = {
                        'session_id': session_id,
                        'last_modified': metadata.get('last_seen') or last_modified,
                        'preview': preview,
                        'message_count': message_count,
                        'cwd': cwd,
                        'project_dir': str(project_dir),  # Always send the project directory path
                    }

                    sessions_in_project.append(session_info)

                if sessions_in_project:
                    directories = {}
                    for session in sessions_in_project:
                        cwd = session.get('cwd', 'unknown')
                        if cwd not in directories:
                            directories[cwd] = []
                        directories[cwd].append(session)

                    projects_data[project_name] = {'directories': directories}

        # Sort sessions by last_modified
        for project in projects_data.values():
            for directory in project['directories'].values():
                # Sort by converting all values to datetime for proper comparison
                def get_sort_key(session):
                    lm = session['last_modified']
                    try:
                        if isinstance(lm, str):
                            return datetime.fromisoformat(lm)
                        elif isinstance(lm, (int, float)):
                            # Handle both seconds and milliseconds timestamps
                            if lm > 10000000000:  # Likely milliseconds
                                return datetime.fromtimestamp(lm / 1000.0)
                            else:
                                return datetime.fromtimestamp(lm)
                        elif isinstance(lm, datetime):
                            return lm
                    except (ValueError, OSError, OverflowError) as e:
                        print(f"Warning: Invalid timestamp for session {session.get('session_id')}: {lm} ({e})")
                    return datetime.min

                directory.sort(key=get_sort_key, reverse=True)

        return {'projects': projects_data, 'ungrouped': []}

    async def get_session_preview(self, session_file: Path) -> str:
        """Extract preview text from session file"""
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
        """Load session history for display"""
        session_id = data.get('session_id')
        if not session_id:
            await self.send_error(websocket, "session_id required")
            return

        print(f"[{datetime.now().isoformat()}] Loading session: {session_id}")

        try:
            # Find session file
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

    async def handle_start_terminal(self, websocket, data: Dict):
        """Start a terminal session with Claude CLI"""
        session_id = data.get('session_id')
        project_dir = data.get('project_dir')
        skip_permissions = data.get('skip_permissions', False)
        use_continue = data.get('use_continue', True)  # Default to --continue
        use_resume = data.get('use_resume', False)  # Keep for backward compatibility
        personal_preferences = data.get('personal_preferences')

        if not session_id:
            await self.send_error(websocket, "session_id required")
            return

        # use_continue takes precedence
        if use_continue:
            use_resume = False

        print(f"[{datetime.now().isoformat()}] Starting terminal for session: {session_id} (skip_permissions={skip_permissions}, use_continue={use_continue}, project_dir={project_dir})")

        try:
            # Validate project_dir if provided
            if project_dir and not os.path.isdir(project_dir):
                print(f"Warning: project_dir '{project_dir}' does not exist, using current directory")
                project_dir = None

            # Create terminal session
            terminal = ClaudeTerminalSession(session_id, project_dir, skip_permissions, use_resume, personal_preferences)
            await terminal.start()

            terminal.websockets.add(websocket)
            self.sessions[session_id] = terminal

            # Start reading output
            asyncio.create_task(self.read_terminal_output(session_id))

            # Track open tab
            self.open_tabs[session_id] = {
                'sessionId': session_id,
                'title': project_dir or session_id[:8],
                'projectDir': project_dir,
                'type': 'claude'
            }

            await self.send_message(websocket, {
                'type': 'terminal_started',
                'session_id': session_id,
                'timestamp': datetime.now().isoformat()
            })

        except Exception as e:
            error_msg = f"Error starting terminal: {str(e)}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            await self.send_error(websocket, error_msg)
            traceback.print_exc()

    async def handle_start_shell(self, websocket, data: Dict):
        """Start a shell terminal session"""
        session_id = data.get('session_id', 'shell')
        print(f"[{datetime.now().isoformat()}] Starting shell terminal with session_id: {session_id}")
        debug_log(f"handle_start_shell called with data: {data}")

        try:
            # Close existing session with this ID if any
            if session_id in self.sessions:
                self.sessions[session_id].close()
                del self.sessions[session_id]

            # Create shell session
            debug_log("Creating ShellSession instance")
            shell = ShellSession()
            debug_log("Starting shell session")
            await shell.start()
            debug_log(f"Shell started with PID: {shell.pid}")

            shell.websockets.add(websocket)
            self.sessions[session_id] = shell
            debug_log(f"Added shell session to sessions dict: {session_id}")

            # Start reading output
            asyncio.create_task(self.read_terminal_output(session_id))
            debug_log("Started read_terminal_output task")

            # Track open tab
            self.open_tabs[session_id] = {
                'sessionId': session_id,
                'title': '🖥️ Shell',
                'projectDir': None,
                'type': 'shell'
            }

            await self.send_message(websocket, {
                'type': 'terminal_started',
                'session_id': session_id,
                'timestamp': datetime.now().isoformat()
            })
            debug_log(f"Shell terminal started successfully: {session_id}")

        except Exception as e:
            error_msg = f"Error starting shell: {e}"
            debug_log(f"Shell start error: {error_msg}\n{traceback.format_exc()}")
            await self.send_error(websocket, error_msg)
            traceback.print_exc()

    async def read_terminal_output(self, session_id: str):
        """Continuously read output from terminal and broadcast to clients"""
        terminal = self.sessions.get(session_id)
        if not terminal:
            return

        while session_id in self.sessions and terminal.websockets:
            try:
                output = await terminal.read_output()
                if output:
                    # Broadcast to all connected clients sequentially to prevent message interleaving
                    message = {
                        'type': 'terminal_output',
                        'session_id': session_id,
                        'output': output,
                        'timestamp': datetime.now().isoformat()
                    }

                    # Send to each websocket one at a time
                    for ws in list(terminal.websockets):
                        try:
                            await self.send_message(ws, message)
                        except websockets.exceptions.ConnectionClosed:
                            terminal.websockets.discard(ws)
                        except Exception as e:
                            print(f"Error broadcasting to websocket: {e}")
                            terminal.websockets.discard(ws)

                    # Small delay after broadcasting to prevent overwhelming the connection
                    await asyncio.sleep(0.01)
                else:
                    await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Error reading terminal output: {e}")
                break

        # Clean up
        if session_id in self.sessions:
            terminal.close()
            del self.sessions[session_id]

    async def handle_start_new_session(self, websocket, data: Dict):
        """Start a new Claude session with a title and optional initial prompt"""
        import uuid

        # Use session_id from client, or generate a new one
        session_id = data.get('session_id')
        if not session_id:
            session_id = str(uuid.uuid4())

        title = data.get('title', 'New Session')
        directory = data.get('directory')
        initial_prompt = data.get('initial_prompt')
        skip_permissions = data.get('skip_permissions', False)
        resume = data.get('resume', False)  # Check if we want to resume

        # Use synced personal preferences from the server
        personal_preferences = self.personal_preferences if self.personal_preferences else None

        print(f"[{datetime.now().isoformat()}] Creating new session: {title} (ID: {session_id}, resume={resume}, prefs={len(personal_preferences) if personal_preferences else 0} chars)")

        try:
            # Validate directory if provided
            if directory and not os.path.isdir(directory):
                print(f"Warning: directory '{directory}' does not exist, using current directory")
                directory = None

            # Create terminal session with or without resume flag
            terminal = ClaudeTerminalSession(session_id, directory, skip_permissions, use_resume=resume, personal_preferences=personal_preferences)

            # Override session_id to None for both fresh sessions and resume menu
            # - For fresh sessions: we don't want to resume anything
            # - For resume: we want to show the interactive menu, not resume a specific (non-existent) session ID
            if not resume:
                terminal.session_id = None  # Start fresh session
            else:
                terminal.session_id = None  # Show resume menu (don't try to resume the client's session_id)

            await terminal.start()

            terminal.websockets.add(websocket)
            self.sessions[session_id] = terminal

            # Start reading output
            asyncio.create_task(self.read_terminal_output(session_id))

            # Track open tab
            self.open_tabs[session_id] = {
                'sessionId': session_id,
                'title': title,
                'projectDir': directory,
                'type': 'claude'
            }

            await self.send_message(websocket, {
                'type': 'terminal_started',
                'session_id': session_id,
                'title': title,
                'timestamp': datetime.now().isoformat()
            })

            # If initial prompt provided, send it after a short delay
            if initial_prompt:
                await asyncio.sleep(1)
                await terminal.write_input(initial_prompt + '\n')

        except Exception as e:
            error_msg = f"Error creating new session: {str(e)}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            await self.send_error(websocket, error_msg)
            traceback.print_exc()

    async def handle_reconnect_session(self, websocket, data: Dict):
        """Reconnect a client to an existing session"""
        session_id = data.get('session_id')

        if not session_id:
            await self.send_error(websocket, "No session_id provided")
            return

        print(f"[{datetime.now().isoformat()}] Reconnecting to session: {session_id}")

        if session_id in self.sessions:
            # Add this websocket to the session
            terminal = self.sessions[session_id]
            terminal.websockets.add(websocket)

            # Notify client that reconnection succeeded
            await self.send_message(websocket, {
                'type': 'session_reconnected',
                'session_id': session_id,
                'timestamp': datetime.now().isoformat()
            })
            print(f"[{datetime.now().isoformat()}] Reconnected to session {session_id}")
        else:
            await self.send_error(websocket, f"Session {session_id} not found on server")

    async def handle_close_session(self, websocket, data: Dict):
        """Close a terminal session"""
        session_id = data.get('session_id')

        if not session_id:
            return

        print(f"[{datetime.now().isoformat()}] Closing session: {session_id}")

        if session_id in self.sessions:
            terminal = self.sessions[session_id]
            terminal.close()
            del self.sessions[session_id]
            print(f"[{datetime.now().isoformat()}] Session {session_id} closed")

        # Remove from open tabs
        if session_id in self.open_tabs:
            del self.open_tabs[session_id]
            print(f"[{datetime.now().isoformat()}] Removed tab: {session_id}")

    async def handle_upload_file(self, websocket, data: Dict):
        """Handle file upload from browser"""
        import base64
        import tempfile

        session_id = data.get('session_id')
        filename = data.get('filename')
        content_base64 = data.get('content')
        file_size = data.get('size', 0)

        if not session_id or session_id not in self.sessions:
            await self.send_error(websocket, "No active terminal session")
            return

        if not filename or not content_base64:
            await self.send_error(websocket, "Missing filename or content")
            return

        print(f"[{datetime.now().isoformat()}] Uploading file: {filename} ({file_size} bytes) to session {session_id}")

        try:
            # Decode base64 content
            file_content = base64.b64decode(content_base64)

            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp_file:
                tmp_file.write(file_content)
                tmp_path = tmp_file.name

            # Send file message to Claude
            terminal = self.sessions[session_id]
            file_message = f"File: {tmp_path}\n"
            await terminal.write_input(file_message)

            await self.send_message(websocket, {
                'type': 'file_uploaded',
                'session_id': session_id,
                'filename': filename,
                'temp_path': tmp_path,
                'timestamp': datetime.now().isoformat()
            })

            print(f"[{datetime.now().isoformat()}] File uploaded successfully: {filename} -> {tmp_path}")

        except Exception as e:
            error_msg = f"Error uploading file: {str(e)}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            await self.send_error(websocket, error_msg)
            traceback.print_exc()

    async def handle_list_directory(self, websocket, data: Dict):
        """List directory contents"""
        import base64

        path = data.get('path', '/')
        session_id = data.get('session_id')

        print(f"[{datetime.now().isoformat()}] Listing directory: {path}")

        try:
            # Expand user home directory
            path = os.path.expanduser(path)

            # Security check - ensure path exists and is readable
            if not os.path.exists(path):
                await self.send_error(websocket, f"Path does not exist: {path}")
                return

            if not os.path.isdir(path):
                await self.send_error(websocket, f"Path is not a directory: {path}")
                return

            # List directory contents
            files = []
            for item in sorted(os.listdir(path)):
                item_path = os.path.join(path, item)
                try:
                    stat_info = os.stat(item_path)
                    is_dir = os.path.isdir(item_path)
                    files.append({
                        'name': item,
                        'path': item_path,
                        'is_directory': is_dir,
                        'size': stat_info.st_size if not is_dir else 0,
                        'modified': stat_info.st_mtime
                    })
                except (PermissionError, OSError) as e:
                    print(f"Warning: Cannot access {item_path}: {e}")
                    continue

            await self.send_message(websocket, {
                'type': 'directory_listing',
                'session_id': session_id,
                'path': path,
                'files': files,
                'timestamp': datetime.now().isoformat()
            })

        except Exception as e:
            error_msg = f"Error listing directory: {str(e)}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            await self.send_error(websocket, error_msg)
            traceback.print_exc()

    async def handle_download_file(self, websocket, data: Dict):
        """Download a file"""
        import base64

        file_path = data.get('path')
        session_id = data.get('session_id')

        print(f"[{datetime.now().isoformat()}] Downloading file: {file_path}")

        try:
            # Expand user home directory
            file_path = os.path.expanduser(file_path)

            # Security checks
            if not os.path.exists(file_path):
                await self.send_error(websocket, f"File does not exist: {file_path}")
                return

            if not os.path.isfile(file_path):
                await self.send_error(websocket, f"Path is not a file: {file_path}")
                return

            # Read file
            with open(file_path, 'rb') as f:
                content = f.read()

            # Encode to base64
            content_base64 = base64.b64encode(content).decode('utf-8')

            await self.send_message(websocket, {
                'type': 'file_download',
                'session_id': session_id,
                'filename': os.path.basename(file_path),
                'content': content_base64,
                'size': len(content),
                'timestamp': datetime.now().isoformat()
            })

            print(f"[{datetime.now().isoformat()}] File downloaded: {file_path} ({len(content)} bytes)")

        except Exception as e:
            error_msg = f"Error downloading file: {str(e)}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            await self.send_error(websocket, error_msg)
            traceback.print_exc()

    async def handle_upload_file_to_path(self, websocket, data: Dict):
        """Upload a file to a specific path"""
        import base64

        target_path = data.get('path')
        filename = data.get('filename')
        content_base64 = data.get('content')
        session_id = data.get('session_id')

        print(f"[{datetime.now().isoformat()}] Uploading file to: {target_path}/{filename}")

        try:
            # Expand user home directory
            target_path = os.path.expanduser(target_path)

            # Decode base64 content
            file_content = base64.b64decode(content_base64)

            # Create full path
            full_path = os.path.join(target_path, filename)

            # Write file
            with open(full_path, 'wb') as f:
                f.write(file_content)

            await self.send_message(websocket, {
                'type': 'file_upload_complete',
                'session_id': session_id,
                'filename': filename,
                'path': full_path,
                'size': len(file_content),
                'timestamp': datetime.now().isoformat()
            })

            print(f"[{datetime.now().isoformat()}] File uploaded: {full_path} ({len(file_content)} bytes)")

        except Exception as e:
            error_msg = f"Error uploading file: {str(e)}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            await self.send_error(websocket, error_msg)
            traceback.print_exc()

    async def handle_terminal_input(self, websocket, data: Dict):
        """Handle input from web client to terminal"""
        session_id = data.get('session_id')
        input_text = data.get('input', '')

        if not session_id or session_id not in self.sessions:
            await self.send_error(websocket, "No active terminal session")
            return

        terminal = self.sessions[session_id]
        await terminal.write_input(input_text)

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

    async def handle_restart_server(self, websocket):
        """Restart the bridge server"""
        try:
            print(f"[{datetime.now().isoformat()}] Restart requested, shutting down...")

            # Send acknowledgment before restarting
            await self.send_message(websocket, {
                'type': 'restart_acknowledged',
                'message': 'Server restarting...',
                'timestamp': datetime.now().isoformat()
            })

            # Give time for message to be sent
            await asyncio.sleep(0.5)

            # Close all sessions
            for session_id in list(self.sessions.keys()):
                await self.cleanup_session(session_id)

            # Exit with code 0 to signal systemd/supervisor to restart
            # Or use os.execv to restart in-place
            os.execv(sys.executable, [sys.executable] + sys.argv)

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error during restart: {e}")
            traceback.print_exc()
            await self.send_error(websocket, f"Error restarting server: {e}")

    async def handle_update_server(self, websocket, data: Dict = None):
        """Update the bridge server from repository or HTTP source and restart"""
        try:
            print(f"[{datetime.now().isoformat()}] Update requested...")

            # Get update source from data if provided
            update_source = data.get('update_source') if data else None

            # Send acknowledgment
            await self.send_message(websocket, {
                'type': 'update_started',
                'message': 'Checking for updates...',
                'timestamp': datetime.now().isoformat()
            })

            # Get the directory where this script is located
            script_dir = Path(__file__).parent.absolute()
            script_path = Path(__file__).absolute()

            update_output = ""
            update_success = False

            # Try git pull first (for development setups)
            if not update_source:
                print(f"[{datetime.now().isoformat()}] Attempting git pull in {script_dir}")

                try:
                    process = await asyncio.create_subprocess_exec(
                        'git', 'pull',
                        cwd=str(script_dir),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await process.communicate()

                    if process.returncode == 0:
                        update_output = stdout.decode().strip()
                        print(f"[{datetime.now().isoformat()}] Git pull successful: {update_output}")
                        update_success = True
                    else:
                        error_msg = stderr.decode() if stderr else "Unknown git error"
                        print(f"[{datetime.now().isoformat()}] Git pull failed: {error_msg}")
                        update_output = f"Git pull failed: {error_msg}"
                except Exception as e:
                    print(f"[{datetime.now().isoformat()}] Git not available: {e}")
                    update_output = f"Git not available: {e}"

            # If git failed or update_source provided, run deployment installer
            if not update_success and update_source:
                print(f"[{datetime.now().isoformat()}] Running deployment installer from {update_source}")

                await self.send_message(websocket, {
                    'type': 'update_progress',
                    'message': f'Running deployment installer from {update_source}...',
                    'timestamp': datetime.now().isoformat()
                })

                try:
                    # Get current machine name and port from command line args
                    machine_name = self.machine_name
                    # Port is in the server config (we need to extract it)
                    # For now, assume 8766 as default
                    import sys
                    ws_port = "8766"
                    for i, arg in enumerate(sys.argv):
                        if arg == '--port' and i + 1 < len(sys.argv):
                            ws_port = sys.argv[i + 1]
                            break

                    # Build the installation command
                    install_cmd = f'curl -fsSL {update_source}/install | SOURCE_SERVER={update_source} MACHINE_NAME="{machine_name}" WS_PORT={ws_port} bash'

                    print(f"[{datetime.now().isoformat()}] Running: {install_cmd}")

                    await self.send_message(websocket, {
                        'type': 'update_progress',
                        'message': f'Installing updates...\nCommand: {install_cmd}',
                        'timestamp': datetime.now().isoformat()
                    })

                    # Execute the installation script
                    process = await asyncio.create_subprocess_shell(
                        install_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await process.communicate()

                    if process.returncode == 0:
                        update_output = stdout.decode().strip()
                        print(f"[{datetime.now().isoformat()}] Installation successful")
                        print(update_output)
                        update_success = True
                    else:
                        error_msg = stderr.decode() if stderr else "Installation failed"
                        update_output = f"Installation failed: {error_msg}"
                        print(f"[{datetime.now().isoformat()}] {update_output}")

                except Exception as e:
                    update_output = f"Installation error: {e}"
                    print(f"[{datetime.now().isoformat()}] {update_output}")

            if not update_success:
                await self.send_error(websocket, f"Update failed: {update_output}")
                return

            # Send update progress
            await self.send_message(websocket, {
                'type': 'update_complete',
                'message': f'Update successful! Service should restart automatically.',
                'timestamp': datetime.now().isoformat()
            })

            # Give time for message to be sent
            await asyncio.sleep(0.5)

            # The install script handles the service restart in non-interactive mode
            # Just log that update completed
            print(f"[{datetime.now().isoformat()}] Update complete. Install script handled service restart.")

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error during update: {e}")
            traceback.print_exc()
            await self.send_error(websocket, f"Error updating server: {e}")

    async def handle_get_version(self, websocket):
        """Return the bridge server version"""
        try:
            await self.send_message(websocket, {
                'type': 'version',
                'version': VERSION,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error getting version: {e}")
            await self.send_error(websocket, f"Error getting version: {e}")

    async def handle_sync_preferences(self, websocket, data: Dict):
        """Sync personal preferences from the web UI and to all existing Claude sessions"""
        try:
            preferences = data.get('preferences', '')
            self.personal_preferences = preferences
            print(f"[{datetime.now().isoformat()}] Personal preferences synced ({len(preferences)} chars)")

            # Send preferences to all existing Claude sessions
            sync_to_existing = data.get('syncToExisting', False)
            if sync_to_existing and preferences.strip():
                synced_count = 0
                for session_id, session in self.sessions.items():
                    # Only sync to Claude sessions, not shell sessions
                    if isinstance(session, ClaudeTerminalSession):
                        try:
                            # Format preferences as a visible message in the terminal
                            prefs_msg = f"\r\n\x1b[36m[System: Personal Preferences updated]\x1b[0m\r\n{preferences}\r\n\x1b[36m[End of Personal Preferences]\x1b[0m\r\n\r\n"

                            # Write to the PTY (which Claude sees)
                            if session.master_fd:
                                os.write(session.master_fd, prefs_msg.encode('utf-8'))
                                synced_count += 1
                                print(f"[{datetime.now().isoformat()}] Synced preferences to session {session_id}")
                        except Exception as e:
                            print(f"[{datetime.now().isoformat()}] Error syncing to session {session_id}: {e}")

                if synced_count > 0:
                    print(f"[{datetime.now().isoformat()}] Synced preferences to {synced_count} existing Claude session(s)")

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error syncing preferences: {e}")
            await self.send_error(websocket, f"Error syncing preferences: {e}")

    async def handle_get_metrics(self, websocket):
        """Get server metrics (CPU, RAM, disk, uptime, network I/O)"""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)

            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_gb = memory.used / (1024**3)
            memory_total_gb = memory.total / (1024**3)

            # Disk usage (root filesystem for main display)
            disk = psutil.disk_usage('/')
            disk_free_gb = disk.free / (1024**3)
            disk_total_gb = disk.total / (1024**3)
            disk_percent = disk.percent

            # All disk partitions for detailed view
            all_disks = []
            for partition in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    all_disks.append({
                        'device': partition.device,
                        'mountpoint': partition.mountpoint,
                        'fstype': partition.fstype,
                        'total_gb': round(usage.total / (1024**3), 2),
                        'used_gb': round(usage.used / (1024**3), 2),
                        'free_gb': round(usage.free / (1024**3), 2),
                        'percent': round(usage.percent, 1)
                    })
                except (PermissionError, OSError):
                    # Skip partitions we can't access
                    continue

            # System uptime
            boot_time = psutil.boot_time()
            uptime_seconds = datetime.now().timestamp() - boot_time
            uptime_days = int(uptime_seconds // 86400)
            uptime_hours = int((uptime_seconds % 86400) // 3600)
            uptime_minutes = int((uptime_seconds % 3600) // 60)
            uptime_str = f"{uptime_days}d {uptime_hours}h {uptime_minutes}m"

            # Network I/O
            net_io = psutil.net_io_counters()
            net_sent_gb = net_io.bytes_sent / (1024**3)
            net_recv_gb = net_io.bytes_recv / (1024**3)

            metrics = {
                'cpu_percent': round(cpu_percent, 1),
                'memory_percent': round(memory_percent, 1),
                'memory_used_gb': round(memory_used_gb, 2),
                'memory_total_gb': round(memory_total_gb, 2),
                'disk_free_gb': round(disk_free_gb, 2),
                'disk_total_gb': round(disk_total_gb, 2),
                'disk_percent': round(disk_percent, 1),
                'all_disks': all_disks,
                'uptime': uptime_str,
                'net_sent_gb': round(net_sent_gb, 2),
                'net_recv_gb': round(net_recv_gb, 2)
            }

            await self.send_message(websocket, {
                'type': 'metrics',
                'data': metrics
            })

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error getting metrics: {e}")
            await self.send_error(websocket, f"Error getting metrics: {e}")

    async def send_message(self, websocket, data: Dict):
        """Send JSON message to websocket"""
        try:
            # Ensure clean JSON encoding with no extra whitespace
            json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            debug_log(f"Sending message: {json_str[:200]}...")
            # Send the message and ensure it's flushed
            await websocket.send(json_str)
            # Add small delay to prevent message concatenation
            await asyncio.sleep(0.001)
        except websockets.exceptions.ConnectionClosed:
            # Connection closed, silently ignore
            pass
        except Exception as e:
            error_msg = f"Error sending message: {e}"
            print(error_msg)
            debug_log(f"Send error details: {traceback.format_exc()}")

    async def send_error(self, websocket, error_msg: str):
        """Send error message to websocket"""
        await self.send_message(websocket, {
            'type': 'error',
            'message': error_msg,
            'timestamp': datetime.now().isoformat()
        })

    async def start(self, host: str, port: int):
        """Start the WebSocket server"""
        print(f"Starting Claude Bridge Server (Terminal Mode)")
        print(f"Machine: {self.machine_name}")
        print(f"Claude Home: {self.claude_home}")
        print(f"Listening on: ws://{host}:{port}")
        print(f"Press Ctrl+C to stop\n")

        async with websockets.serve(self.handle_client, host, port):
            await asyncio.Future()  # Run forever


def main():
    parser = argparse.ArgumentParser(
        description='Remote Claude CLI Bridge Server (Terminal Mode)',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8766, help='Port to listen on (default: 8766)')
    parser.add_argument('--machine-name', required=True, help='Name identifier for this machine')
    parser.add_argument('--claude-home', default='~/.claude', help='Claude CLI home directory (default: ~/.claude)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    # Set global debug flag
    global DEBUG_MODE
    DEBUG_MODE = args.debug

    try:
        server = ClaudeBridgeTerminalServer(
            machine_name=args.machine_name,
            claude_home=args.claude_home
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
