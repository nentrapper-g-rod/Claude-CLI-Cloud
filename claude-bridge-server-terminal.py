#!/usr/bin/env python3
"""
Remote Claude CLI Bridge Server (Terminal Mode)
Purpose: WebSocket server that relays between web UI and actual Claude CLI process
"""

VERSION = "2.12.0"  # Simple git push integration for version tracking

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
import subprocess
import shlex
import time
import aiohttp
import re

# Import conversation database
try:
    from conversation_db import get_db
    CONVERSATION_DB_AVAILABLE = True
except ImportError:
    print("WARNING: conversation-db module not found. Conversation history will not be saved.")
    CONVERSATION_DB_AVAILABLE = False

try:
    import aiofiles
    import psutil
    from aiohttp import web
except ImportError:
    print("ERROR: Required dependencies not installed.")
    print("Please install: pip install aiofiles websockets psutil aiohttp")
    sys.exit(1)

# Global debug flag
DEBUG_MODE = False

def debug_log(message: str):
    """Print debug messages if debug mode is enabled"""
    if DEBUG_MODE:
        timestamp = datetime.now().isoformat()
        print(f"[DEBUG {timestamp}] {message}", flush=True)

def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape sequences and control characters from text"""
    # Remove all ANSI escape sequences (ESC[...m, ESC]...BEL, etc)
    ansi_escape = re.compile(r'''
        \x1B  # ESC
        (?:   # 7-bit C1 Fe (except CSI)
            [@-Z\\-_]
        |     # or CSI sequences
            \[
            [0-?]*  # Parameter bytes
            [ -/]*  # Intermediate bytes
            [@-~]   # Final byte
        |     # or OSC sequences
            \]
            .*?
            (?:\x07|\x1b\x5c)  # BEL or ESC backslash
        )
    ''', re.VERBOSE)
    text = ansi_escape.sub('', text)

    # Remove other control characters (keep newlines, tabs, carriage returns)
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)

    # Clean up multiple spaces and empty lines
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(line for line in lines if line)

    return text.strip()


class TmuxSession:
    """Base class for tmux-based terminal sessions"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        # Add timestamp to make session name unique each time
        timestamp = str(time.time()).replace('.', '')
        self.tmux_session_name = f"claude-bridge-{session_id}-{timestamp}"
        self.websockets = set()
        self.cols = 80
        self.rows = 24
        self.output_task = None
        self.running = False

    def _run_tmux_command(self, *args, capture_output=True):
        """Run a tmux command"""
        cmd = ['tmux'] + list(args)
        try:
            if capture_output:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                return result.stdout, result.returncode
            else:
                subprocess.run(cmd, timeout=5)
                return None, 0
        except subprocess.TimeoutExpired:
            print(f"[{datetime.now().isoformat()}] Tmux command timed out: {' '.join(cmd)}")
            return None, -1
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error running tmux command: {e}")
            return None, -1

    async def create_tmux_session(self, command: str, cwd: str = None):
        """Create a new tmux session with the given command"""
        # Create a detached tmux session
        create_args = [
            'new-session',
            '-d',  # Detached
            '-s', self.tmux_session_name,  # Session name
            '-x', str(self.cols),  # Width
            '-y', str(self.rows),  # Height
        ]

        if cwd:
            create_args.extend(['-c', cwd])  # Working directory

        # Add the command to run
        create_args.append(command)

        _, returncode = self._run_tmux_command(*create_args, capture_output=False)

        if returncode == 0:
            print(f"[{datetime.now().isoformat()}] Created tmux session: {self.tmux_session_name}")
            self.running = True
            return True
        else:
            print(f"[{datetime.now().isoformat()}] Failed to create tmux session: {self.tmux_session_name}")
            return False

    async def resize(self, cols: int, rows: int):
        """Resize the tmux pane"""
        self.cols = cols
        self.rows = rows

        _, returncode = self._run_tmux_command(
            'resize-pane',
            '-t', self.tmux_session_name,
            '-x', str(cols),
            '-y', str(rows),
            capture_output=False
        )

        if returncode == 0:
            print(f"[{datetime.now().isoformat()}] Resized tmux session {self.tmux_session_name} to {cols}x{rows}")

    async def send_keys(self, keys: str):
        """Send keys to the tmux session"""
        # Use send-keys with -l flag for literal text (no special processing)
        _, returncode = self._run_tmux_command(
            'send-keys',
            '-t', self.tmux_session_name,
            '-l', keys,
            capture_output=False
        )

        if returncode != 0:
            print(f"[{datetime.now().isoformat()}] Error sending keys to tmux session")

    async def capture_pane(self):
        """Capture the visible content of the tmux pane"""
        output, returncode = self._run_tmux_command(
            'capture-pane',
            '-t', self.tmux_session_name,
            '-p',  # Print to stdout
            '-e',  # Include escape sequences
        )

        if returncode == 0 and output:
            return output
        return None

    async def read_output(self):
        """Read incremental output from tmux (this is a simplified version)"""
        # For now, we'll just return None and rely on periodic capture
        # A more sophisticated version would track the last read position
        return None

    async def write_input(self, text: str):
        """Write input to the tmux session"""
        await self.send_keys(text)

    def close(self):
        """Close the tmux session"""
        self.running = False
        _, returncode = self._run_tmux_command(
            'kill-session',
            '-t', self.tmux_session_name,
            capture_output=False
        )

        if returncode == 0:
            print(f"[{datetime.now().isoformat()}] Killed tmux session: {self.tmux_session_name}")


class ClaudeTerminalSession:
    """Manages a tmux-wrapped PTY session with Claude CLI"""

    def __init__(self, session_id: str, project_dir: str = None, skip_permissions: bool = False, use_resume: bool = False, personal_preferences: str = None, connection_name: str = None):
        self.session_id = session_id
        self.project_dir = project_dir
        self.skip_permissions = skip_permissions
        self.use_resume = use_resume
        self.personal_preferences = personal_preferences
        self.connection_name = connection_name or "Local CLI"
        self.master_fd = None
        self.pid = None
        self.websockets = set()
        # Add timestamp to make session name unique each time
        timestamp = str(time.time()).replace('.', '')
        self.tmux_session_name = f"claude-bridge-{session_id}-{timestamp}"

    async def start(self):
        """Start Claude CLI in a tmux session, then attach via PTY"""
        # Build Claude CLI arguments as a list
        claude_args = ['claude']

        if self.use_resume:
            claude_args.append('--resume')
        elif self.session_id:
            claude_args.extend(['--resume', self.session_id])

        if self.skip_permissions:
            claude_args.append('--dangerously-skip-permissions')

        # Personal preferences disabled for session entry
        # if self.personal_preferences and self.personal_preferences.strip():
        #     system_prompt = f"Personal preferences to consider:\n\n{self.personal_preferences}"
        #     claude_args.extend(['--append-system-prompt', system_prompt])

        # If project directory is specified, change to it first
        if self.project_dir and os.path.isdir(self.project_dir):
            # Use bash -c with cd, passing arguments through the environment is safer
            # But actually, let's just set the working directory for the tmux session
            tmux_cmd = claude_args
            working_dir = self.project_dir
        else:
            tmux_cmd = claude_args
            working_dir = None

        # Create detached tmux session with Claude CLI
        # Note: We need to run through bash -l to get proper PATH with nvm, etc.
        try:
            # Check if session already exists
            check_result = subprocess.run(
                ['tmux', 'has-session', '-t', self.tmux_session_name],
                capture_output=True,
                timeout=2
            )

            session_exists = (check_result.returncode == 0)

            if not session_exists:
                tmux_base_cmd = [
                    'tmux', 'new-session',
                    '-d',  # Detached
                    '-s', self.tmux_session_name,
                    '-x', '80',  # Initial width (will be resized later)
                    '-y', '24',  # Initial height
                ]

                # Add working directory if specified
                if working_dir:
                    tmux_base_cmd.extend(['-c', working_dir])

                # Set connection name environment variable for the session
                # We need to do this before starting the command
                tmux_base_cmd.extend(['-e', f'CLAUDE_CONNECTION_NAME={self.connection_name}'])

                # Set MCP configuration path (if it exists)
                mcp_config_path = os.path.expanduser('~/.config/claude/mcp_config.json')
                if os.path.exists(mcp_config_path):
                    tmux_base_cmd.extend(['-e', f'MCP_CONFIG_FILE={mcp_config_path}'])

                # Run command through bash -l to get proper PATH
                # Instead of trying to quote everything, exec the command directly
                # by building an array and using bash's "$@" expansion
                # This avoids all quoting issues
                final_cmd = tmux_base_cmd + ['bash', '-l', '-c', 'exec "$@"', '--'] + claude_args

                subprocess.run(final_cmd, check=True, timeout=5)
                print(f"[{datetime.now().isoformat()}] Created tmux session: {self.tmux_session_name} with connection name: {self.connection_name}")

                # Configure tmux status bar position (top instead of bottom)
                subprocess.run([
                    'tmux', 'set-option', '-t', self.tmux_session_name,
                    'status-position', 'top'
                ], timeout=2)

                # Enable mouse support for scrolling with Shift+scroll
                subprocess.run([
                    'tmux', 'set-option', '-t', self.tmux_session_name,
                    'mouse', 'on'
                ], timeout=2)
            else:
                print(f"[{datetime.now().isoformat()}] Attaching to existing tmux session: {self.tmux_session_name}")

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Failed to create tmux session: {e}")
            raise

        # Small delay to let tmux session start
        await asyncio.sleep(0.1)

        # Now create a PTY that attaches to the tmux session
        self.pid, self.master_fd = pty.fork()

        if self.pid == 0:
            # Child process - attach to tmux session
            os.environ['TERM'] = 'xterm-256color'
            os.execvp('tmux', ['tmux', 'attach', '-t', self.tmux_session_name])
        else:
            # Parent process - make non-blocking
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            print(f"[{datetime.now().isoformat()}] Started Claude CLI for session {self.session_id} (PID: {self.pid}) in tmux")

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

    async def resize_terminal(self, cols: int, rows: int):
        """Resize both the PTY and the underlying tmux session"""
        # Resize the PTY
        try:
            winsize = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error resizing PTY: {e}")

        # Also resize the tmux pane
        try:
            subprocess.run([
                'tmux', 'resize-pane',
                '-t', self.tmux_session_name,
                '-x', str(cols),
                '-y', str(rows)
            ], timeout=2)
            print(f"[{datetime.now().isoformat()}] Resized tmux session {self.tmux_session_name} to {cols}x{rows}")
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error resizing tmux pane: {e}")

    def close(self):
        """Close the PTY and tmux session"""
        if self.master_fd:
            os.close(self.master_fd)
        if self.pid:
            try:
                os.kill(self.pid, 15)  # SIGTERM
            except:
                pass

        # Kill the tmux session
        try:
            subprocess.run(['tmux', 'kill-session', '-t', self.tmux_session_name], timeout=2)
            print(f"[{datetime.now().isoformat()}] Killed tmux session: {self.tmux_session_name}")
        except:
            pass


class ShellSession:
    """Manages a tmux-wrapped PTY session with a regular shell"""

    def __init__(self, session_id: str = None):
        self.session_id = session_id or f"shell-{datetime.now().timestamp()}"
        self.master_fd = None
        self.pid = None
        self.websockets = set()
        # Add timestamp to make session name unique each time
        timestamp = str(time.time()).replace('.', '')
        self.tmux_session_name = f"claude-bridge-{self.session_id}-{timestamp}"

    async def start(self):
        """Start a bash shell in a tmux session, then attach via PTY"""
        # Create detached tmux session with bash
        try:
            # Check if session already exists
            check_result = subprocess.run(
                ['tmux', 'has-session', '-t', self.tmux_session_name],
                capture_output=True,
                timeout=2
            )

            session_exists = (check_result.returncode == 0)

            if not session_exists:
                subprocess.run([
                    'tmux', 'new-session',
                    '-d',  # Detached
                    '-s', self.tmux_session_name,
                    '-x', '80',  # Initial width
                    '-y', '24',  # Initial height
                    'bash'
                ], check=True, timeout=5)
                print(f"[{datetime.now().isoformat()}] Created tmux shell session: {self.tmux_session_name}")

                # Configure tmux status bar position (top instead of bottom)
                subprocess.run([
                    'tmux', 'set-option', '-t', self.tmux_session_name,
                    'status-position', 'top'
                ], timeout=2)

                # Enable mouse support for scrolling with Shift+scroll
                subprocess.run([
                    'tmux', 'set-option', '-t', self.tmux_session_name,
                    'mouse', 'on'
                ], timeout=2)
            else:
                print(f"[{datetime.now().isoformat()}] Attaching to existing tmux shell session: {self.tmux_session_name}")

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Failed to create tmux shell session: {e}")
            raise

        # Small delay to let tmux session start
        await asyncio.sleep(0.1)

        # Create a PTY that attaches to the tmux session
        self.pid, self.master_fd = pty.fork()

        if self.pid == 0:
            # Child process - attach to tmux session
            os.environ['TERM'] = 'xterm-256color'
            os.execvp('tmux', ['tmux', 'attach', '-t', self.tmux_session_name])
        else:
            # Parent process - make non-blocking
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            print(f"[{datetime.now().isoformat()}] Started shell session {self.session_id} (PID: {self.pid}) in tmux")

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

    async def resize_terminal(self, cols: int, rows: int):
        """Resize both the PTY and the underlying tmux session"""
        # Resize the PTY
        try:
            winsize = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error resizing PTY: {e}")

        # Also resize the tmux pane
        try:
            subprocess.run([
                'tmux', 'resize-pane',
                '-t', self.tmux_session_name,
                '-x', str(cols),
                '-y', str(rows)
            ], timeout=2)
            print(f"[{datetime.now().isoformat()}] Resized tmux shell session {self.tmux_session_name} to {cols}x{rows}")
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error resizing tmux pane: {e}")

    def close(self):
        """Close the PTY and tmux session"""
        if self.master_fd:
            os.close(self.master_fd)
        if self.pid:
            try:
                os.kill(self.pid, 15)  # SIGTERM
            except:
                pass

        # Kill the tmux session
        try:
            subprocess.run(['tmux', 'kill-session', '-t', self.tmux_session_name], timeout=2)
            print(f"[{datetime.now().isoformat()}] Killed tmux shell session: {self.tmux_session_name}")
        except:
            pass


class ConversationMonitor:
    """Monitor conversation JSONL files and sync to central database"""

    def __init__(self, claude_home: Path, machine_name: str, conversation_api_url: str = 'http://localhost:8889'):
        self.claude_home = claude_home
        self.machine_name = machine_name
        self.conversation_api_url = conversation_api_url
        self.monitored_files = {}  # session_id -> {path, last_size, last_sync}
        self.monitor_task = None
        self.disable_compaction = False

    async def start_monitoring(self):
        """Start monitoring conversation files"""
        self.monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop_monitoring(self):
        """Stop monitoring"""
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while True:
            try:
                await self._check_conversations()
                await asyncio.sleep(5)  # Check every 5 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[{datetime.now().isoformat()}] Error in conversation monitor: {e}")
                await asyncio.sleep(5)

    async def _check_conversations(self):
        """Check for new or updated conversation files"""
        projects_dir = self.claude_home / 'projects'
        if not projects_dir.exists():
            return

        # Scan all project directories for JSONL files
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            for jsonl_file in project_dir.glob('*.jsonl'):
                session_id = jsonl_file.stem
                file_path = str(jsonl_file)

                # Check if file is new or modified
                try:
                    file_stat = jsonl_file.stat()
                    current_size = file_stat.st_size

                    if session_id not in self.monitored_files:
                        # New file
                        self.monitored_files[session_id] = {
                            'path': file_path,
                            'last_size': 0,
                            'last_sync': 0
                        }

                    file_info = self.monitored_files[session_id]

                    # Check if file has grown
                    if current_size > file_info['last_size']:
                        await self._sync_conversation(session_id, jsonl_file, project_dir.name)
                        file_info['last_size'] = current_size
                        file_info['last_sync'] = time.time()

                except Exception as e:
                    print(f"[{datetime.now().isoformat()}] Error checking file {jsonl_file}: {e}")

    async def _sync_conversation(self, session_id: str, jsonl_file: Path, project: str):
        """Sync a conversation file to the central database"""
        if self.disable_compaction:
            return  # Skip if compaction is disabled

        try:
            # Parse JSONL file to extract messages
            messages = []
            cwd = None

            async with aiofiles.open(jsonl_file, 'r') as f:
                async for line in f:
                    try:
                        entry = json.loads(line)

                        # Extract user/assistant messages (ignore file-history-snapshot)
                        if entry.get('type') in ['user', 'assistant']:
                            content = ''
                            if 'text' in entry:
                                content = entry['text']
                            elif 'content' in entry:
                                if isinstance(entry['content'], str):
                                    content = entry['content']
                                elif isinstance(entry['content'], list):
                                    # Extract text from content blocks
                                    for block in entry['content']:
                                        if isinstance(block, dict) and block.get('type') == 'text':
                                            content += block.get('text', '')

                            if content:
                                messages.append({
                                    'message_id': entry.get('messageId'),
                                    'role': entry['type'],
                                    'content': content,
                                    'timestamp': entry.get('timestamp', datetime.now().isoformat())
                                })

                        # Extract working directory if available
                        if not cwd and 'cwd' in entry:
                            cwd = entry['cwd']

                    except json.JSONDecodeError:
                        continue

            if messages:
                # Send to central API
                data = {
                    'session_id': session_id,
                    'connection_name': self.machine_name,
                    'project': project,
                    'cwd': cwd,
                    'messages': messages
                }

                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.post(
                            f'{self.conversation_api_url}/api/conversations/sync',
                            json=data,
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as response:
                            if response.status == 200:
                                result = await response.json()
                                print(f"[{datetime.now().isoformat()}] Synced {result.get('message_count', 0)} messages for session {session_id}")
                            else:
                                print(f"[{datetime.now().isoformat()}] Failed to sync conversation: HTTP {response.status}")
                    except asyncio.TimeoutError:
                        print(f"[{datetime.now().isoformat()}] Timeout syncing conversation for session {session_id}")
                    except Exception as e:
                        print(f"[{datetime.now().isoformat()}] Error syncing conversation: {e}")

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error processing conversation file {jsonl_file}: {e}")


class ClaudeBridgeTerminalServer:
    """WebSocket server that bridges web UI to Claude CLI terminal"""

    def __init__(self, machine_name: str, claude_home: str, conversation_api_url: str = 'http://localhost:8889'):
        self.machine_name = machine_name
        self.claude_home = Path(claude_home).expanduser()
        self.clients = set()
        self.client_connection_names = {}  # websocket -> connection_name mapping
        self.sessions = {}  # session_id -> ClaudeTerminalSession or ShellSession
        self.session_cache = {}
        self.open_tabs = {}  # session_id -> {sessionId, title, projectDir, type}
        self.personal_preferences = ''  # Store synced personal preferences
        self.conversation_monitor = ConversationMonitor(self.claude_home, machine_name, conversation_api_url)

        # Initialize conversation database
        if CONVERSATION_DB_AVAILABLE:
            try:
                self.conv_db = get_db()
                print(f"[{datetime.now().isoformat()}] Conversation database initialized")
            except Exception as e:
                print(f"[{datetime.now().isoformat()}] Failed to initialize conversation database: {e}")
                self.conv_db = None
        else:
            self.conv_db = None

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

            # Auto-configure MCP server on first connection
            await self.ensure_mcp_configured()

            # Run init script if provided by client
            await self.run_init_script(websocket)

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
            # Clean up connection name mapping
            self.client_connection_names.pop(websocket, None)
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
        elif msg_type == 'rename_file':
            await self.handle_rename_file(websocket, data)
        elif msg_type == 'delete_file':
            await self.handle_delete_file(websocket, data)
        elif msg_type == 'zip_directory':
            await self.handle_zip_directory(websocket, data)
        elif msg_type == 'terminal_input':
            await self.handle_terminal_input(websocket, data)
        elif msg_type == 'resize_terminal':
            await self.handle_resize_terminal(websocket, data)
        elif msg_type == 'get_projects':
            await self.handle_get_projects(websocket)
        elif msg_type == 'restart_server':
            await self.handle_restart_server(websocket)
        elif msg_type == 'history_sync':
            await self.handle_history_sync(websocket)
        elif msg_type == 'update_server':
            await self.handle_update_server(websocket, data)
        elif msg_type == 'get_version':
            await self.handle_get_version(websocket)
        elif msg_type == 'sync_preferences':
            await self.handle_sync_preferences(websocket, data)
        elif msg_type == 'get_metrics':
            await self.handle_get_metrics(websocket)
        elif msg_type == 'update_session_title':
            await self.handle_update_session_title(websocket, data)
        elif msg_type == 'get_custom_projects':
            await self.handle_get_custom_projects(websocket)
        elif msg_type == 'create_project':
            await self.handle_create_project(websocket, data)
        elif msg_type == 'assign_session_to_project':
            await self.handle_assign_session_to_project(websocket, data)
        elif msg_type == 'delete_project':
            await self.handle_delete_project(websocket, data)
        elif msg_type == 'init_script':
            await self.execute_init_script(data.get('script', ''))
        elif msg_type == 'update_config':
            await self.handle_update_config(websocket, data)
        elif msg_type == 'set_connection_name':
            await self.handle_set_connection_name(websocket, data)
        elif msg_type == 'git_push_auto':
            await self.handle_git_push_auto(websocket, data)
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

        # Load custom projects to match sessions with projects
        custom_projects = []
        projects_file = self.claude_home / "custom_projects.json"
        if projects_file.exists():
            try:
                async with aiofiles.open(projects_file, 'r') as f:
                    content = await f.read()
                    custom_projects = json.loads(content)
                print(f"[{datetime.now().isoformat()}] Loaded {len(custom_projects)} custom projects")
            except (json.JSONDecodeError, IOError) as e:
                print(f"[{datetime.now().isoformat()}] Error loading custom projects: {e}")
                custom_projects = []

        # Load custom titles
        custom_titles = {}
        titles_file = self.claude_home / "session_titles.json"
        if titles_file.exists():
            try:
                async with aiofiles.open(titles_file, 'r') as f:
                    content = await f.read()
                    custom_titles = json.loads(content)
                print(f"[{datetime.now().isoformat()}] Loaded {len(custom_titles)} custom titles")
            except (json.JSONDecodeError, IOError) as e:
                print(f"[{datetime.now().isoformat()}] Error loading custom titles: {e}")
                custom_titles = {}

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

                    # Find matching custom projects based on cwd
                    matched_projects = []
                    for proj in custom_projects:
                        # Support both 'directories' (new format) and 'working_directory' (old format)
                        proj_dirs = proj.get('directories', [])
                        if not proj_dirs and proj.get('working_directory'):
                            proj_dirs = [proj['working_directory']]

                        # Check if session's cwd matches any project directory
                        for proj_dir in proj_dirs:
                            if cwd != 'unknown' and cwd.startswith(proj_dir):
                                matched_projects.append({
                                    'id': proj.get('id'),
                                    'name': proj.get('name'),
                                    'color': proj.get('color', '#4a9eff')
                                })
                                break

                    session_info = {
                        'session_id': session_id,
                        'last_modified': metadata.get('last_seen') or last_modified,
                        'preview': preview,
                        'message_count': message_count,
                        'cwd': cwd,
                        'project_dir': str(project_dir),  # Always send the project directory path
                        'custom_title': custom_titles.get(session_id),  # Add custom title if exists
                        'matched_projects': matched_projects  # Add matched custom projects
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

            # Get connection name for this websocket
            connection_name = self.client_connection_names.get(websocket, self.machine_name)

            # Create terminal session
            terminal = ClaudeTerminalSession(session_id, project_dir, skip_permissions, use_resume, personal_preferences, connection_name)
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
            shell = ShellSession(session_id=session_id)
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
                    # Save to conversation database (skip shell sessions)
                    if not isinstance(terminal, ShellSession):
                        self.save_conversation_to_db(session_id, output, role='assistant')

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

        # Personal preferences disabled for session entry
        personal_preferences = None

        print(f"[{datetime.now().isoformat()}] Creating new session: {title} (ID: {session_id}, resume={resume})")

        try:
            # Validate directory if provided
            if directory and not os.path.isdir(directory):
                print(f"Warning: directory '{directory}' does not exist, using current directory")
                directory = None

            # Get connection name for this websocket
            connection_name = self.client_connection_names.get(websocket, self.machine_name)

            # Create terminal session with or without resume flag
            terminal = ClaudeTerminalSession(session_id, directory, skip_permissions, use_resume=resume, personal_preferences=personal_preferences, connection_name=connection_name)

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

        file_path = data.get('file_path') or data.get('path')
        session_id = data.get('session_id')

        print(f"[{datetime.now().isoformat()}] Download request - file_path: {file_path}, session_id: {session_id}, data: {data}")

        if not file_path:
            await self.send_error(websocket, f"No file path provided in download request. Data received: {data}")
            return

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

    async def handle_rename_file(self, websocket, data: Dict):
        """Rename a file or directory"""
        old_path = data.get('old_path')
        new_name = data.get('new_name')
        is_directory = data.get('is_directory', False)
        session_id = data.get('session_id')

        print(f"[{datetime.now().isoformat()}] Renaming: {old_path} -> {new_name}")

        try:
            # Expand user home directory
            old_path = os.path.expanduser(old_path)

            # Security checks
            if not os.path.exists(old_path):
                await self.send_error(websocket, f"Path does not exist: {old_path}")
                return

            # Create new path (same directory, new name)
            parent_dir = os.path.dirname(old_path)
            new_path = os.path.join(parent_dir, new_name)

            # Check if new name already exists
            if os.path.exists(new_path):
                await self.send_error(websocket, f"A file or directory named '{new_name}' already exists")
                return

            # Rename
            os.rename(old_path, new_path)

            await self.send_message(websocket, {
                'type': 'file_renamed',
                'session_id': session_id,
                'old_path': old_path,
                'new_path': new_path,
                'new_name': new_name,
                'is_directory': is_directory,
                'timestamp': datetime.now().isoformat()
            })

            print(f"[{datetime.now().isoformat()}] Renamed: {old_path} -> {new_path}")

        except Exception as e:
            error_msg = f"Error renaming: {str(e)}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            await self.send_error(websocket, error_msg)
            traceback.print_exc()

    async def handle_delete_file(self, websocket, data: Dict):
        """Delete a file or directory"""
        import shutil

        file_path = data.get('path')
        is_directory = data.get('is_directory', False)
        session_id = data.get('session_id')

        print(f"[{datetime.now().isoformat()}] Deleting: {file_path}")

        try:
            # Expand user home directory
            file_path = os.path.expanduser(file_path)

            # Security checks
            if not os.path.exists(file_path):
                await self.send_error(websocket, f"Path does not exist: {file_path}")
                return

            # Delete
            if is_directory:
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)

            await self.send_message(websocket, {
                'type': 'file_deleted',
                'session_id': session_id,
                'path': file_path,
                'filename': os.path.basename(file_path),
                'is_directory': is_directory,
                'timestamp': datetime.now().isoformat()
            })

            print(f"[{datetime.now().isoformat()}] Deleted: {file_path}")

        except Exception as e:
            error_msg = f"Error deleting: {str(e)}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            await self.send_error(websocket, error_msg)
            traceback.print_exc()

    async def handle_zip_directory(self, websocket, data: Dict):
        """Zip a directory and send it for download"""
        import base64
        import zipfile
        import tempfile

        dir_path = data.get('path')
        dir_name = data.get('name')
        session_id = data.get('session_id')

        print(f"[{datetime.now().isoformat()}] Zipping directory: {dir_path}")

        try:
            # Expand user home directory
            dir_path = os.path.expanduser(dir_path)

            # Security checks
            if not os.path.exists(dir_path):
                await self.send_error(websocket, f"Directory does not exist: {dir_path}")
                return

            if not os.path.isdir(dir_path):
                await self.send_error(websocket, f"Path is not a directory: {dir_path}")
                return

            # Create temporary zip file
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_file:
                tmp_path = tmp_file.name

            try:
                # Create zip file
                with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    # Walk through directory
                    for root, dirs, files in os.walk(dir_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            # Calculate archive name (relative to the directory being zipped)
                            arcname = os.path.relpath(file_path, dir_path)
                            zipf.write(file_path, arcname)

                # Read zip file content
                with open(tmp_path, 'rb') as f:
                    zip_content = f.read()

                # Encode to base64
                content_base64 = base64.b64encode(zip_content).decode('utf-8')

                # Send zip file
                await self.send_message(websocket, {
                    'type': 'zip_ready',
                    'session_id': session_id,
                    'filename': f"{dir_name}.zip",
                    'content': content_base64,
                    'size': len(zip_content),
                    'timestamp': datetime.now().isoformat()
                })

                print(f"[{datetime.now().isoformat()}] Zipped: {dir_path} ({len(zip_content)} bytes)")

            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        except Exception as e:
            error_msg = f"Error zipping directory: {str(e)}"
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

        # Save user input to conversation database (skip shell sessions)
        if input_text.strip() and not isinstance(terminal, ShellSession):
            self.save_conversation_to_db(session_id, input_text, role='user')

        await terminal.write_input(input_text)

    async def handle_resize_terminal(self, websocket, data: Dict):
        """Handle terminal resize from web client"""
        session_id = data.get('session_id')
        cols = data.get('cols', 80)
        rows = data.get('rows', 24)

        if not session_id or session_id not in self.sessions:
            return

        session = self.sessions[session_id]

        # Call the session's resize_terminal method if it exists
        if hasattr(session, 'resize_terminal'):
            await session.resize_terminal(cols, rows)
        elif hasattr(session, 'master_fd') and session.master_fd:
            # Fallback for old-style sessions without resize_terminal method
            try:
                winsize = struct.pack('HHHH', rows, cols, 0, 0)
                fcntl.ioctl(session.master_fd, termios.TIOCSWINSZ, winsize)
                print(f"[{datetime.now().isoformat()}] Resized terminal {session_id} to {cols}x{rows}")
            except Exception as e:
                print(f"[{datetime.now().isoformat()}] Error resizing terminal {session_id}: {e}")

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

    async def handle_history_sync(self, websocket):
        """Import CLI history into conversation database"""
        try:
            print(f"[{datetime.now().isoformat()}] History sync requested...")

            # Send starting message
            await self.send_message(websocket, {
                'type': 'history_sync_started',
                'message': 'Starting history import...',
                'timestamp': datetime.now().isoformat()
            })

            # Import history
            try:
                from import_cli_history import import_history_file
                history_path = Path.home() / '.claude' / 'history.jsonl'

                imported, skipped = import_history_file(history_path, connection_name=self.machine_name)

                # Send success message
                await self.send_message(websocket, {
                    'type': 'history_sync_complete',
                    'message': f'History sync complete! Imported: {imported}, Skipped: {skipped}',
                    'imported': imported,
                    'skipped': skipped,
                    'timestamp': datetime.now().isoformat()
                })

            except Exception as e:
                error_msg = f"Error importing history: {str(e)}"
                print(f"[{datetime.now().isoformat()}] {error_msg}")
                await self.send_message(websocket, {
                    'type': 'history_sync_error',
                    'message': error_msg,
                    'timestamp': datetime.now().isoformat()
                })

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error during history sync: {e}")
            traceback.print_exc()

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
                        stderr=asyncio.subprocess.STDOUT  # Merge stderr into stdout
                    )
                    stdout, _ = await process.communicate()

                    if process.returncode == 0:
                        update_output = stdout.decode().strip()
                        print(f"[{datetime.now().isoformat()}] Installation successful")
                        print(update_output)
                        update_success = True
                    else:
                        update_output = stdout.decode().strip() if stdout else "Installation failed"
                        print(f"[{datetime.now().isoformat()}] Installation failed: {update_output}")

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
            preferences_obj = data.get('preferences', {})
            # Extract personalPreferences string from the preferences object
            if isinstance(preferences_obj, dict):
                preferences = preferences_obj.get('personalPreferences', '')
                disable_compaction = preferences_obj.get('disableCompaction', False)
            else:
                preferences = preferences_obj if isinstance(preferences_obj, str) else ''
                disable_compaction = False

            self.personal_preferences = preferences
            self.conversation_monitor.disable_compaction = disable_compaction
            print(f"[{datetime.now().isoformat()}] Personal preferences synced ({len(preferences)} chars), disable_compaction={disable_compaction}")

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

    async def handle_update_session_title(self, websocket, data: Dict):
        """Update custom title for a session"""
        try:
            session_id = data.get('session_id')
            custom_title = data.get('custom_title')

            if not session_id:
                await self.send_error(websocket, "Missing session_id")
                return

            print(f"[{datetime.now().isoformat()}] Updating title for session {session_id}: {custom_title}")

            # Store custom titles in a JSON file
            titles_file = self.claude_home / "session_titles.json"
            titles = {}

            # Load existing titles
            if titles_file.exists():
                try:
                    async with aiofiles.open(titles_file, 'r') as f:
                        content = await f.read()
                        titles = json.loads(content)
                except (json.JSONDecodeError, IOError) as e:
                    print(f"[{datetime.now().isoformat()}] Error reading titles file: {e}")
                    titles = {}

            # Update or remove title
            if custom_title:
                titles[session_id] = custom_title
            elif session_id in titles:
                del titles[session_id]

            # Save titles
            try:
                async with aiofiles.open(titles_file, 'w') as f:
                    await f.write(json.dumps(titles, indent=2))

                await self.send_message(websocket, {
                    'type': 'session_title_updated',
                    'session_id': session_id,
                    'custom_title': custom_title
                })
                print(f"[{datetime.now().isoformat()}] Title updated successfully")

            except IOError as e:
                error_msg = f"Error saving title: {e}"
                print(f"[{datetime.now().isoformat()}] {error_msg}")
                await self.send_error(websocket, error_msg)

        except Exception as e:
            error_msg = f"Error updating session title: {e}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            traceback.print_exc()
            await self.send_error(websocket, error_msg)

    async def handle_get_custom_projects(self, websocket):
        """Get custom projects list"""
        try:
            projects_file = self.claude_home / "custom_projects.json"
            projects = []

            if projects_file.exists():
                try:
                    async with aiofiles.open(projects_file, 'r') as f:
                        content = await f.read()
                        projects = json.loads(content)
                except (json.JSONDecodeError, IOError) as e:
                    print(f"[{datetime.now().isoformat()}] Error reading projects file: {e}")
                    projects = []

            await self.send_message(websocket, {
                'type': 'custom_projects',
                'projects': projects
            })

        except Exception as e:
            error_msg = f"Error getting projects: {e}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            traceback.print_exc()
            await self.send_error(websocket, error_msg)

    async def handle_create_project(self, websocket, data: Dict):
        """Create a new custom project"""
        try:
            name = data.get('name')
            description = data.get('description', '')
            color = data.get('color', '#4a9eff')
            working_directory = data.get('working_directory', '')

            if not name:
                await self.send_error(websocket, "Missing project name")
                return

            print(f"[{datetime.now().isoformat()}] Creating project: {name}")

            # Load existing projects
            projects_file = self.claude_home / "custom_projects.json"
            projects = []

            if projects_file.exists():
                try:
                    async with aiofiles.open(projects_file, 'r') as f:
                        content = await f.read()
                        projects = json.loads(content)
                except (json.JSONDecodeError, IOError) as e:
                    print(f"[{datetime.now().isoformat()}] Error reading projects file: {e}")
                    projects = []

            # Create new project
            import uuid
            new_project = {
                'id': str(uuid.uuid4()),
                'name': name,
                'description': description,
                'color': color,
                'working_directory': working_directory,
                'sessions': [],
                'created': datetime.now().isoformat()
            }

            projects.append(new_project)

            # Save projects
            try:
                async with aiofiles.open(projects_file, 'w') as f:
                    await f.write(json.dumps(projects, indent=2))

                # Send updated projects list
                await self.send_message(websocket, {
                    'type': 'custom_projects',
                    'projects': projects
                })
                print(f"[{datetime.now().isoformat()}] Project created successfully")

            except IOError as e:
                error_msg = f"Error saving project: {e}"
                print(f"[{datetime.now().isoformat()}] {error_msg}")
                await self.send_error(websocket, error_msg)

        except Exception as e:
            error_msg = f"Error creating project: {e}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            traceback.print_exc()
            await self.send_error(websocket, error_msg)

    async def handle_assign_session_to_project(self, websocket, data: Dict):
        """Assign or remove a session from a project"""
        try:
            project_id = data.get('project_id')
            session_id = data.get('session_id')
            action = data.get('action', 'add')  # 'add' or 'remove'

            if not project_id or not session_id:
                await self.send_error(websocket, "Missing project_id or session_id")
                return

            print(f"[{datetime.now().isoformat()}] {action} session {session_id} to/from project {project_id}")

            # Load projects
            projects_file = self.claude_home / "custom_projects.json"
            projects = []

            if projects_file.exists():
                try:
                    async with aiofiles.open(projects_file, 'r') as f:
                        content = await f.read()
                        projects = json.loads(content)
                except (json.JSONDecodeError, IOError) as e:
                    print(f"[{datetime.now().isoformat()}] Error reading projects file: {e}")
                    await self.send_error(websocket, "Error reading projects")
                    return

            # Find project and update sessions
            project_found = False
            for project in projects:
                if project['id'] == project_id:
                    project_found = True
                    if 'sessions' not in project:
                        project['sessions'] = []

                    if action == 'add':
                        if session_id not in project['sessions']:
                            project['sessions'].append(session_id)
                    elif action == 'remove':
                        if session_id in project['sessions']:
                            project['sessions'].remove(session_id)
                    break

            if not project_found:
                await self.send_error(websocket, "Project not found")
                return

            # Save projects
            try:
                async with aiofiles.open(projects_file, 'w') as f:
                    await f.write(json.dumps(projects, indent=2))

                # Send updated projects list
                await self.send_message(websocket, {
                    'type': 'custom_projects',
                    'projects': projects
                })
                print(f"[{datetime.now().isoformat()}] Session assignment updated")

            except IOError as e:
                error_msg = f"Error saving project: {e}"
                print(f"[{datetime.now().isoformat()}] {error_msg}")
                await self.send_error(websocket, error_msg)

        except Exception as e:
            error_msg = f"Error assigning session: {e}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            traceback.print_exc()
            await self.send_error(websocket, error_msg)

    async def handle_delete_project(self, websocket, data: Dict):
        """Delete a custom project"""
        try:
            project_id = data.get('project_id')

            if not project_id:
                await self.send_error(websocket, "Missing project_id")
                return

            print(f"[{datetime.now().isoformat()}] Deleting project: {project_id}")

            # Load projects
            projects_file = self.claude_home / "custom_projects.json"
            projects = []

            if projects_file.exists():
                try:
                    async with aiofiles.open(projects_file, 'r') as f:
                        content = await f.read()
                        projects = json.loads(content)
                except (json.JSONDecodeError, IOError) as e:
                    print(f"[{datetime.now().isoformat()}] Error reading projects file: {e}")
                    await self.send_error(websocket, "Error reading projects")
                    return

            # Remove project
            projects = [p for p in projects if p['id'] != project_id]

            # Save projects
            try:
                async with aiofiles.open(projects_file, 'w') as f:
                    await f.write(json.dumps(projects, indent=2))

                # Send updated projects list
                await self.send_message(websocket, {
                    'type': 'custom_projects',
                    'projects': projects
                })
                print(f"[{datetime.now().isoformat()}] Project deleted successfully")

            except IOError as e:
                error_msg = f"Error saving projects: {e}"
                print(f"[{datetime.now().isoformat()}] {error_msg}")
                await self.send_error(websocket, error_msg)

        except Exception as e:
            error_msg = f"Error deleting project: {e}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            traceback.print_exc()
            await self.send_error(websocket, error_msg)

    async def handle_update_config(self, websocket, data: Dict):
        """Update Claude Code config.json with personal preferences"""
        try:
            personal_preferences = data.get('personal_preferences', '')
            remote_username = data.get('remote_username')

            print(f"[{datetime.now().isoformat()}] Updating Claude Code config...")

            # Determine the correct home directory
            if remote_username:
                config_path = Path(f"/home/{remote_username}/.config/claude-code/config.json")
            else:
                config_path = Path.home() / ".config" / "claude-code" / "config.json"

            # Check if we have permission before trying to create
            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                error_msg = f"Permission denied: Cannot create {config_path.parent}. Bridge server needs write permission or run with correct user."
                print(f"[{datetime.now().isoformat()}] {error_msg}")
                await self.send_error(websocket, error_msg)
                return

            # Load existing config or create new one
            config = {}
            if config_path.exists():
                try:
                    async with aiofiles.open(config_path, 'r') as f:
                        content = await f.read()
                        config = json.loads(content)
                except (json.JSONDecodeError, IOError) as e:
                    print(f"[{datetime.now().isoformat()}] Error reading config, creating new: {e}")

            # Update personal preferences
            config['personalPreferences'] = personal_preferences

            # Write config
            async with aiofiles.open(config_path, 'w') as f:
                await f.write(json.dumps(config, indent=2))

            print(f"[{datetime.now().isoformat()}] Config updated at: {config_path}")

            await self.send_message(websocket, {
                'type': 'config_updated',
                'success': True,
                'path': str(config_path)
            })

        except PermissionError as e:
            error_msg = f"Permission denied updating config: {e}. Check file permissions or remote username setting."
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            traceback.print_exc()
            await self.send_error(websocket, error_msg)
        except Exception as e:
            error_msg = f"Error updating config: {e}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            traceback.print_exc()
            await self.send_error(websocket, error_msg)

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

    async def handle_set_connection_name(self, websocket, data: Dict):
        """Store the connection name for this WebSocket client"""
        connection_name = data.get('connection_name')
        if connection_name:
            self.client_connection_names[websocket] = connection_name
            print(f"[{datetime.now().isoformat()}] Set connection name for client {id(websocket)}: {connection_name}")

    async def handle_git_push_auto(self, websocket, data: Dict):
        """Auto-commit and push all changes to git"""
        try:
            cwd = data.get('cwd')
            project_name = data.get('project_name', 'Unknown')
            github_token = data.get('github_token', '')
            repo_url = data.get('repo_url', '')

            if not cwd:
                await self.send_error(websocket, "Missing project directory")
                return

            # Generate timestamp for commit message
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_msg = f"Auto-save {timestamp}"

            print(f"[{datetime.now().isoformat()}] Git push for {project_name} at {cwd}")

            # Setup commands
            commands = []

            # If GitHub token is provided, configure git remote with token
            if github_token and repo_url:
                # Extract owner/repo from URL (e.g., https://github.com/user/repo.git)
                import re
                match = re.search(r'github\.com[:/]([^/]+)/([^/\.]+)', repo_url)
                if match:
                    owner, repo = match.groups()
                    # Set up authenticated remote URL
                    auth_url = f"https://{github_token}@github.com/{owner}/{repo}.git"
                    commands.append(f"cd {shlex.quote(cwd)} && git remote set-url origin {shlex.quote(auth_url)} 2>/dev/null || git remote add origin {shlex.quote(auth_url)}")

            # Execute git commands
            commands.extend([
                f"cd {shlex.quote(cwd)} && git add -A",
                f"cd {shlex.quote(cwd)} && git commit -m {shlex.quote(commit_msg)}",
                f"cd {shlex.quote(cwd)} && git push"
            ])

            output_lines = []
            success = True

            for cmd in commands:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT
                )
                stdout, _ = await proc.communicate()
                output = stdout.decode().strip()

                if output:
                    output_lines.append(output)

                # Check if command failed
                if proc.returncode != 0:
                    # Allow "nothing to commit" as success
                    if "nothing to commit" in output.lower() or "working tree clean" in output.lower():
                        output_lines.append("✓ No changes to commit")
                        success = True
                        break
                    else:
                        success = False
                        break

            # Send result back to client
            await self.send_message(websocket, {
                'type': 'git_push_result',
                'success': success,
                'project_name': project_name,
                'output': '\n'.join(output_lines),
                'timestamp': datetime.now().isoformat()
            })

        except Exception as e:
            error_msg = f"Git push failed: {e}"
            print(f"[{datetime.now().isoformat()}] {error_msg}")
            traceback.print_exc()
            await self.send_error(websocket, error_msg)

    def _find_project_for_directory(self, directory: str) -> Optional[str]:
        """Find project name if directory is within a project's directories"""
        if not directory:
            return None

        try:
            projects_file = Path(self.claude_home) / 'custom_projects.json'
            if not projects_file.exists():
                return None

            with open(projects_file, 'r') as f:
                projects = json.load(f)

            directory_path = Path(directory).resolve()

            for project in projects:
                project_dirs = project.get('directories', [])
                for proj_dir in project_dirs:
                    try:
                        proj_path = Path(proj_dir).resolve()
                        # Check if directory is within project directory
                        if directory_path == proj_path or proj_path in directory_path.parents:
                            return project.get('name')
                    except Exception:
                        continue

        except Exception as e:
            debug_log(f"Error finding project for directory: {e}")

        return None

    def save_conversation_to_db(self, session_id: str, content: str, role: str = 'assistant'):
        """Save conversation message to database - DISABLED (use conversation hooks instead)"""
        # This old method is disabled - conversation logging now happens via Claude CLI hooks
        # which provide better structured data and avoid duplicate/fragmented messages
        return

    async def ensure_mcp_configured(self):
        """Ensure MCP server and hooks are configured on this machine"""
        try:
            script_dir = Path(__file__).parent.absolute()
            install_script = script_dir / "install-mcp-config.sh"

            if not install_script.exists():
                print(f"[{datetime.now().isoformat()}] MCP install script not found, skipping auto-config")
                return

            # Check if MCP is already configured
            try:
                process = await asyncio.create_subprocess_exec(
                    'claude', 'mcp', 'list',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                output = stdout.decode()

                # If conversation-history is already configured and connected, skip
                if 'conversation-history' in output and '✓ Connected' in output:
                    print(f"[{datetime.now().isoformat()}] MCP already configured and connected")
                    return

            except Exception as e:
                print(f"[{datetime.now().isoformat()}] Could not check MCP status: {e}")

            # Run the install script
            print(f"[{datetime.now().isoformat()}] Configuring MCP server...")
            process = await asyncio.create_subprocess_exec(
                'bash', str(install_script),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                print(f"[{datetime.now().isoformat()}] MCP configuration successful")
            else:
                print(f"[{datetime.now().isoformat()}] MCP configuration failed: {stderr.decode()}")

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error ensuring MCP configured: {e}")

    async def run_init_script(self, websocket):
        """Download and run init.sh from UI server"""
        try:
            # Download init.sh from UI server
            init_url = "http://100.94.187.56:8888/init.sh"

            print(f"[{datetime.now().isoformat()}] Downloading init script from {init_url}")

            # Download init.sh
            process = await asyncio.create_subprocess_exec(
                'curl', '-fsSL', init_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                print(f"[{datetime.now().isoformat()}] Failed to download init script: {stderr.decode()}")
                return

            script_content = stdout.decode()
            if not script_content.strip():
                print(f"[{datetime.now().isoformat()}] Init script is empty, skipping")
                return

            # Save to local file
            script_dir = Path(__file__).parent.absolute()
            script_file = script_dir / "init-from-ui.sh"
            script_file.write_text(script_content)
            script_file.chmod(0o755)

            print(f"[{datetime.now().isoformat()}] Executing init script in background...")

            # Execute script in background (non-blocking)
            process = await asyncio.create_subprocess_exec(
                'bash', str(script_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Don't wait for completion - let it run in background
            print(f"[{datetime.now().isoformat()}] Init script started (PID: {process.pid})")

            # Schedule cleanup and logging in background
            asyncio.create_task(self._monitor_init_script(process, script_file))

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error running init script: {e}")

    async def _monitor_init_script(self, process, script_file):
        """Monitor init script completion in background"""
        try:
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                print(f"[{datetime.now().isoformat()}] Init script completed successfully")
                if stdout:
                    print(f"[{datetime.now().isoformat()}] Init script output:\n{stdout.decode()}")
            else:
                print(f"[{datetime.now().isoformat()}] Init script failed: {stderr.decode()}")

            # Clean up temp file
            if script_file.exists():
                script_file.unlink()

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error monitoring init script: {e}")

    async def handle_http_get_projects(self, request):
        """HTTP API: Get all projects"""
        try:
            projects_file = Path(self.claude_home) / 'custom_projects.json'
            if projects_file.exists():
                async with aiofiles.open(projects_file, 'r') as f:
                    content = await f.read()
                    projects = json.loads(content)
            else:
                projects = []
            return web.json_response(projects, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_create_project(self, request):
        """HTTP API: Create new project"""
        try:
            data = await request.json()
            projects_file = Path(self.claude_home) / 'custom_projects.json'

            if projects_file.exists():
                async with aiofiles.open(projects_file, 'r') as f:
                    content = await f.read()
                    projects = json.loads(content)
            else:
                projects = []

            new_project = {
                'id': f"project_{datetime.now().timestamp()}_{os.urandom(4).hex()}",
                'name': data.get('name'),
                'description': data.get('description', ''),
                'directories': data.get('directories', []),
                'connection_index': data.get('connection_index'),
                'repo': data.get('repo', ''),
                'link': data.get('link', ''),
                'color': data.get('color', '#4a9eff'),
                'sessions': []
            }

            projects.append(new_project)

            async with aiofiles.open(projects_file, 'w') as f:
                await f.write(json.dumps(projects, indent=2))

            return web.json_response(new_project, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_update_project(self, request):
        """HTTP API: Update entire project"""
        try:
            project_id = request.match_info['project_id']
            data = await request.json()
            projects_file = Path(self.claude_home) / 'custom_projects.json'

            async with aiofiles.open(projects_file, 'r') as f:
                content = await f.read()
                projects = json.loads(content)

            for project in projects:
                if project['id'] == project_id:
                    project['name'] = data.get('name', project['name'])
                    project['description'] = data.get('description', project.get('description', ''))
                    project['directories'] = data.get('directories', project.get('directories', []))
                    project['connection_index'] = data.get('connection_index', project.get('connection_index'))
                    project['repo'] = data.get('repo', project.get('repo', ''))
                    project['link'] = data.get('link', project.get('link', ''))
                    project['color'] = data.get('color', project.get('color', '#4a9eff'))
                    break

            async with aiofiles.open(projects_file, 'w') as f:
                await f.write(json.dumps(projects, indent=2))

            return web.json_response({'success': True}, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_update_directory(self, request):
        """HTTP API: Update project directory"""
        try:
            project_id = request.match_info['project_id']
            data = await request.json()
            projects_file = Path(self.claude_home) / 'custom_projects.json'

            async with aiofiles.open(projects_file, 'r') as f:
                content = await f.read()
                projects = json.loads(content)

            for project in projects:
                if project['id'] == project_id:
                    project['working_directory'] = data.get('working_directory', '')
                    break

            async with aiofiles.open(projects_file, 'w') as f:
                await f.write(json.dumps(projects, indent=2))

            return web.json_response({'success': True}, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_update_sessions(self, request):
        """HTTP API: Update project sessions"""
        try:
            project_id = request.match_info['project_id']
            data = await request.json()
            projects_file = Path(self.claude_home) / 'custom_projects.json'

            async with aiofiles.open(projects_file, 'r') as f:
                content = await f.read()
                projects = json.loads(content)

            for project in projects:
                if project['id'] == project_id:
                    if 'sessions' not in project:
                        project['sessions'] = []

                    session_id = data.get('session_id')
                    action = data.get('action')

                    if action == 'add' and session_id not in project['sessions']:
                        project['sessions'].append(session_id)
                    elif action == 'remove' and session_id in project['sessions']:
                        project['sessions'].remove(session_id)
                    break

            async with aiofiles.open(projects_file, 'w') as f:
                await f.write(json.dumps(projects, indent=2))

            return web.json_response({'success': True}, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_delete_project(self, request):
        """HTTP API: Delete project"""
        try:
            project_id = request.match_info['project_id']
            projects_file = Path(self.claude_home) / 'custom_projects.json'

            async with aiofiles.open(projects_file, 'r') as f:
                content = await f.read()
                projects = json.loads(content)

            projects = [p for p in projects if p['id'] != project_id]

            async with aiofiles.open(projects_file, 'w') as f:
                await f.write(json.dumps(projects, indent=2))

            return web.json_response({'success': True}, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_get_connections(self, request):
        """HTTP API: Get all connections"""
        try:
            connections_file = Path(self.claude_home) / 'connections.json'
            if connections_file.exists():
                async with aiofiles.open(connections_file, 'r') as f:
                    content = await f.read()
                    connections = json.loads(content)
            else:
                connections = []
            return web.json_response(connections, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_save_connections(self, request):
        """HTTP API: Save connections"""
        try:
            data = await request.json()
            connections_file = Path(self.claude_home) / 'connections.json'

            async with aiofiles.open(connections_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))

            return web.json_response({'success': True}, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_get_preferences(self, request):
        """HTTP API: Get preferences"""
        try:
            prefs_file = Path(self.claude_home) / 'preferences.json'
            if prefs_file.exists():
                async with aiofiles.open(prefs_file, 'r') as f:
                    content = await f.read()
                    preferences = json.loads(content)
            else:
                preferences = {
                    'personalPreferences': '',
                    'openTabs': {},
                    'sidebarWidth': 300
                }
            return web.json_response(preferences, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_save_preferences(self, request):
        """HTTP API: Save preferences"""
        try:
            data = await request.json()
            prefs_file = Path(self.claude_home) / 'preferences.json'

            async with aiofiles.open(prefs_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))

            return web.json_response({'success': True}, headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers={'Access-Control-Allow-Origin': '*'})

    async def handle_http_options(self, request):
        """Handle CORS preflight"""
        return web.Response(headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        })

    async def handle_http_log_chat(self, request):
        """Log chat messages from Claude Code CLI hooks"""
        try:
            data = await request.json()

            # Extract message data
            role = data.get('role', 'user')
            content = data.get('content', '')
            session_id = data.get('session_id', 'claude-cli')
            tool_name = data.get('tool')

            if not content and not tool_name:
                return web.json_response(
                    {'error': 'Missing content or tool_name'},
                    status=400,
                    headers={'Access-Control-Allow-Origin': '*'}
                )

            # Format the content
            if tool_name:
                formatted_content = f"[Tool: {tool_name}]"
            else:
                formatted_content = strip_ansi_codes(content)

            # Save to conversation database
            if self.conv_db:
                self.save_conversation_to_db(session_id, formatted_content, role=role)
                print(f"[{datetime.now().isoformat()}] Logged {role} message from Claude CLI: {formatted_content[:50]}...")

            return web.json_response(
                {'success': True},
                headers={'Access-Control-Allow-Origin': '*'}
            )

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error logging chat: {e}")
            traceback.print_exc()
            return web.json_response(
                {'error': str(e)},
                status=500,
                headers={'Access-Control-Allow-Origin': '*'}
            )

    async def handle_http_get_sessions_grouped(self, request):
        """Get conversation sessions grouped by connection and directory"""
        try:
            if not CONVERSATION_DB_AVAILABLE:
                return web.json_response(
                    {'error': 'Conversation database not available'},
                    status=503,
                    headers={'Access-Control-Allow-Origin': '*'}
                )

            db = get_db()
            grouped_sessions = db.get_sessions_grouped(limit=1000)

            return web.json_response(
                grouped_sessions,
                headers={'Access-Control-Allow-Origin': '*'}
            )

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error getting grouped sessions: {e}")
            traceback.print_exc()
            return web.json_response(
                {'error': str(e)},
                status=500,
                headers={'Access-Control-Allow-Origin': '*'}
            )

    async def handle_http_get_session_messages(self, request):
        """Get messages for a specific session"""
        try:
            if not CONVERSATION_DB_AVAILABLE:
                return web.json_response(
                    {'error': 'Conversation database not available'},
                    status=503,
                    headers={'Access-Control-Allow-Origin': '*'}
                )

            session_id = request.match_info.get('session_id')
            if not session_id:
                return web.json_response(
                    {'error': 'Missing session_id'},
                    status=400,
                    headers={'Access-Control-Allow-Origin': '*'}
                )

            db = get_db()
            messages = db.get_session_messages(session_id, limit=10000)

            return web.json_response(
                {'messages': messages},
                headers={'Access-Control-Allow-Origin': '*'}
            )

        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error getting session messages: {e}")
            traceback.print_exc()
            return web.json_response(
                {'error': str(e)},
                status=500,
                headers={'Access-Control-Allow-Origin': '*'}
            )

    async def _transcript_sync_loop(self):
        """Periodically sync transcript files to conversation database"""
        import sys
        sys.path.insert(0, str(Path.home() / '.claude-bridge'))

        while True:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds

                if not CONVERSATION_DB_AVAILABLE or not self.conv_db:
                    continue

                # Find all transcript files
                projects_dir = self.claude_home / 'projects'
                if not projects_dir.exists():
                    continue

                for project_dir in projects_dir.iterdir():
                    if not project_dir.is_dir():
                        continue

                    for jsonl_file in project_dir.glob('*.jsonl'):
                        try:
                            session_id = jsonl_file.stem

                            # Read transcript and extract new assistant messages
                            with open(jsonl_file, 'r') as f:
                                lines = f.readlines()

                            # Get existing assistant message UUIDs from DB
                            existing_messages = self.conv_db.get_session_messages(session_id, limit=10000)
                            existing_uuids = set()
                            for msg in existing_messages:
                                if msg.get('role') == 'assistant':
                                    metadata = json.loads(msg.get('metadata', '{}'))
                                    uuid = metadata.get('uuid')
                                    if uuid:
                                        existing_uuids.add(uuid)

                            # Collect new assistant messages
                            new_messages = []
                            for line in lines:
                                try:
                                    entry = json.loads(line.strip())
                                    if entry.get('type') == 'assistant':
                                        entry_uuid = entry.get('uuid')
                                        if entry_uuid in existing_uuids:
                                            continue

                                        message = entry.get('message', {})
                                        if message.get('role') == 'assistant':
                                            content_blocks = message.get('content', [])
                                            full_content = json.dumps(content_blocks)

                                            if content_blocks:
                                                new_messages.append({
                                                    'content': full_content,
                                                    'uuid': entry_uuid,
                                                    'timestamp': entry.get('timestamp')
                                                })
                                except json.JSONDecodeError:
                                    continue

                            # Save new messages
                            if new_messages:
                                messages_to_save = []
                                for msg in new_messages:
                                    messages_to_save.append({
                                        'role': 'assistant',
                                        'content': msg['content'],
                                        'timestamp': msg.get('timestamp') or datetime.now(timezone.utc).isoformat(),
                                        'metadata': {
                                            'event': 'TranscriptSync',
                                            'project': project_dir.name,
                                            'cwd': str(project_dir),
                                            'uuid': msg['uuid'],
                                            'content_type': 'full'
                                        }
                                    })

                                if messages_to_save:
                                    self.conv_db.add_messages(
                                        session_id=session_id,
                                        connection_name=self.machine_name,
                                        messages=messages_to_save,
                                        project=project_dir.name,
                                        cwd=str(project_dir)
                                    )
                                    print(f"[{datetime.now().isoformat()}] Synced {len(messages_to_save)} new assistant messages for session {session_id[:8]}")

                        except Exception as e:
                            # Silent errors for individual files
                            pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[{datetime.now().isoformat()}] Error in transcript sync: {e}")

    async def start(self, host: str, port: int):
        """Start the WebSocket server and HTTP API server"""
        print(f"Starting Claude Bridge Server (Terminal Mode)")
        print(f"Machine: {self.machine_name}")
        print(f"Claude Home: {self.claude_home}")
        print(f"WebSocket: ws://{host}:{port}")
        print(f"HTTP API: http://{host}:8887/api")
        print(f"Press Ctrl+C to stop\n")

        # Start HTTP API server
        app = web.Application()
        app.router.add_get('/api/projects', self.handle_http_get_projects)
        app.router.add_post('/api/projects', self.handle_http_create_project)
        app.router.add_put('/api/projects/{project_id}', self.handle_http_update_project)
        app.router.add_put('/api/projects/{project_id}/directory', self.handle_http_update_directory)
        app.router.add_put('/api/projects/{project_id}/sessions', self.handle_http_update_sessions)
        app.router.add_delete('/api/projects/{project_id}', self.handle_http_delete_project)
        app.router.add_get('/api/connections', self.handle_http_get_connections)
        app.router.add_post('/api/connections', self.handle_http_save_connections)
        app.router.add_get('/api/preferences', self.handle_http_get_preferences)
        app.router.add_post('/api/preferences', self.handle_http_save_preferences)
        app.router.add_post('/api/log', self.handle_http_log_chat)
        app.router.add_get('/api/sessions/grouped', self.handle_http_get_sessions_grouped)
        app.router.add_get('/api/conversations/{session_id}', self.handle_http_get_session_messages)
        app.router.add_options('/api/log', self.handle_http_options)
        app.router.add_options('/api/sessions/grouped', self.handle_http_options)
        app.router.add_options('/api/conversations/{session_id}', self.handle_http_options)
        app.router.add_options('/api/projects', self.handle_http_options)
        app.router.add_options('/api/projects/{project_id}', self.handle_http_options)
        app.router.add_options('/api/projects/{project_id}/directory', self.handle_http_options)
        app.router.add_options('/api/projects/{project_id}/sessions', self.handle_http_options)
        app.router.add_options('/api/connections', self.handle_http_options)
        app.router.add_options('/api/preferences', self.handle_http_options)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, 8887)
        await site.start()

        # Start conversation monitor - DISABLED: Now using MCP server for conversation history
        # await self.conversation_monitor.start_monitoring()
        print(f"Conversation monitor: DISABLED (using MCP server)\n")

        # Start transcript sync task
        asyncio.create_task(self._transcript_sync_loop())
        print(f"Transcript sync task started\n")

        # Start WebSocket server
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
