#!/usr/bin/env python3
"""
Claude CLI Hook for Conversation Logging (OPTIMIZED)
Captures user prompts and assistant responses and saves to database
Also sends to central server for aggregation - ALL ASYNC/NON-BLOCKING
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
import urllib.request
import urllib.error
import subprocess
import threading
import re

# Add the path to conversation_db module
# Auto-detect if we're in /opt/Claude-CLI-Cloud or ~/.claude-bridge
import os
from pathlib import Path
if Path('/opt/Claude-CLI-Cloud/conversation_db.py').exists():
    sys.path.insert(0, '/opt/Claude-CLI-Cloud')
else:
    sys.path.insert(0, str(Path.home() / '.claude-bridge'))

# Central server for conversation aggregation
CENTRAL_SERVER = os.environ.get('CLAUDE_CENTRAL_SERVER', 'http://100.94.187.56:8891')

# Cache for server availability (avoid repeated connection attempts)
_server_available_cache = {'available': None, 'last_check': 0}

def is_central_server():
    """Check if this machine IS the central server to avoid duplicate writes"""
    import socket
    try:
        # Get all local IP addresses
        hostname = socket.gethostname()
        local_ips = socket.gethostbyname_ex(hostname)[2]

        # Extract IP from CENTRAL_SERVER URL
        server_host = CENTRAL_SERVER.split('://')[1].split(':')[0]

        # If central server is localhost or matches our IP, we ARE the central server
        if server_host in ['localhost', '127.0.0.1'] or server_host in local_ips:
            return True

        # Also check via socket connection to get all interfaces
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        our_ip = s.getsockname()[0]
        s.close()

        return server_host == our_ip
    except:
        return False

def is_server_available():
    """Check if central server is available (with caching to avoid repeated checks)"""
    import time

    current_time = time.time()
    cache_duration = 60  # Cache for 60 seconds

    # Use cached result if available and recent
    if _server_available_cache['available'] is not None:
        if current_time - _server_available_cache['last_check'] < cache_duration:
            # Return cached result immediately - no logging needed (reduces noise)
            return _server_available_cache['available']

    # Quick check if server is reachable
    try:
        req = urllib.request.Request(f'{CENTRAL_SERVER}/api/connections', method='HEAD')
        with urllib.request.urlopen(req, timeout=0.5) as response:
            available = response.status == 200
    except Exception as e:
        available = False

    _server_available_cache['available'] = available
    _server_available_cache['last_check'] = current_time
    return available

def send_to_central_server_async(session_data):
    """Send session data to central server asynchronously (non-blocking)"""
    async_log(f"send_to_central_server_async called with event: {session_data.get('event', 'unknown')}")
    def _send():
        import time
        start_time = time.time()
        try:
            # Use synchronous logging for debugging since async threads might not complete
            def sync_log(msg):
                try:
                    if Path('/opt/Claude-CLI-Cloud/conversation_db.py').exists():
                        log_path = Path('/opt/Claude-CLI-Cloud') / 'hook-debug.log'
                    else:
                        log_path = Path.home() / '.claude-bridge' / 'hook-debug.log'
                    with open(log_path, 'a') as f:
                        f.write(f"[{datetime.now().isoformat()}] {msg}\n")
                except:
                    pass

            sync_log("_send thread started")
            # Don't send if we ARE the central server or server is unavailable
            sync_log(f"Checking is_central_server()...")
            is_central = is_central_server()
            sync_log(f"is_central_server() = {is_central}")
            if is_central:
                sync_log("Skipping send: This IS the central server")
                return

            sync_log(f"Checking is_server_available()...")
            server_available = is_server_available()
            sync_log(f"is_server_available() = {server_available}")
            if not server_available:
                sync_log("Skipping send: Central server unavailable")
                return

            sync_log(f"Preparing to send data to {CENTRAL_SERVER}/api/conversations/sync")
            data = json.dumps(session_data).encode('utf-8')
            sync_log(f"Data prepared, size: {len(data)} bytes")
            req = urllib.request.Request(
                f'{CENTRAL_SERVER}/api/conversations/sync',
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            sync_log(f"POST request created, opening connection...")
            with urllib.request.urlopen(req, timeout=2) as response:
                status = response.status
                sync_log(f"Sent to central server: {status}")
                return  # Success
        except Exception as e:
            elapsed = time.time() - start_time
            sync_log(f"Failed to send to central server after {elapsed:.2f}s: {e}")

    # Run in background thread so it doesn't block
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()

def normalize_path(path):
    """Normalize path for comparison - remove leading slashes and convert to lowercase"""
    if not path:
        return ""
    # Remove leading double slashes
    path = re.sub(r'^/+', '/', path)
    # Convert forward slashes to a common format for comparison
    return path.lower().strip('/')

def paths_match(session_cwd, project_dir):
    """Check if session cwd matches or starts with project directory"""
    session_norm = normalize_path(session_cwd)
    project_norm = normalize_path(project_dir)

    # Direct match
    if session_norm.startswith(project_norm):
        return True

    # Try replacing hyphens with slashes and vice versa
    project_with_slashes = project_norm.replace('-', '/')
    project_with_hyphens = project_norm.replace('/', '-')

    if session_norm.startswith(project_with_slashes):
        return True
    if session_norm.startswith(project_with_hyphens):
        return True

    return False

def async_log(message):
    """Non-blocking debug logging"""
    def _log():
        try:
            # Auto-detect log path based on where conversation_db.py is installed
            if Path('/opt/Claude-CLI-Cloud/conversation_db.py').exists():
                debug_log = Path('/opt/Claude-CLI-Cloud') / 'hook-debug.log'
            else:
                debug_log = Path.home() / '.claude-bridge' / 'hook-debug.log'
            with open(debug_log, 'a') as f:
                f.write(f"[{datetime.now().isoformat()}] {message}\n")
        except:
            pass  # Silently fail
    thread = threading.Thread(target=_log, daemon=True)
    thread.start()

try:
    from conversation_db import get_db

    # Read hook data from stdin
    hook_data = json.load(sys.stdin)

    # Debug logging (async, non-blocking)
    async_log(f"Hook event: {hook_data.get('hook_event_name')}")

    event_name = hook_data.get('hook_event_name', '')

    # Get session/project info
    cwd = hook_data.get('cwd', os.getcwd())
    project = hook_data.get('project_name', cwd)

    # Use Claude CLI's actual session_id
    session_id = hook_data.get('session_id', f"claude-cli-{abs(hash(cwd)) % 1000000}")

    # Get connection name from environment variable (set by bridge) or auto-detect from hostname
    connection_name = os.environ.get('CLAUDE_CONNECTION_NAME')
    if not connection_name:
        # Not running through bridge - tag with hostname to differentiate servers
        import socket
        hostname = socket.gethostname()
        # Map known hostnames to friendly names
        hostname_map = {
            'recycle': 'Recycle Server',
            'steel': 'Steel Server',
            'cm-webserver': 'CM Webserver',
            'ip-172-26-13-164': 'CM Webserver'  # AWS instance hostname
        }
        connection_name = hostname_map.get(hostname.lower(), hostname)

    db = get_db()

    # Auto-tag projects based on directory (with flexible path matching)
    project_tags = []
    try:
        custom_projects_path = Path.home() / '.claude' / 'custom_projects.json'
        if custom_projects_path.exists():
            with open(custom_projects_path, 'r') as f:
                custom_projects = json.load(f)
                for proj in custom_projects:
                    # Check if cwd matches any project directories
                    proj_dirs = proj.get('directories', [])
                    if proj.get('working_directory'):
                        proj_dirs.append(proj['working_directory'])

                    for proj_dir in proj_dirs:
                        if cwd and paths_match(cwd, proj_dir):
                            project_tags.append({
                                'id': proj['id'],
                                'name': proj['name'],
                                'color': proj.get('color', '#4a9eff')
                            })
                            break
    except Exception as e:
        async_log(f"Error loading project tags: {e}")

    # Ensure session exists (with project tags)
    db.upsert_session(
        session_id=session_id,
        connection_name=connection_name,
        project=project,
        cwd=cwd,
        project_tags=project_tags
    )

    # Send session info to central server (async, non-blocking)
    send_to_central_server_async({
        'session_id': session_id,
        'connection_name': connection_name,
        'project': project,
        'cwd': cwd,
        'event': event_name
    })

    # Handle different event types
    if event_name == 'UserPromptSubmit':
        # Save user message
        prompt = hook_data.get('prompt', '')
        if prompt:
            # Use UTC timestamp to match assistant message timestamps
            from datetime import timezone
            utc_timestamp = datetime.now(timezone.utc).isoformat()

            message_data = [{
                'role': 'user',
                'content': prompt,
                'timestamp': utc_timestamp,
                'metadata': {
                    'event': 'UserPromptSubmit',
                    'project': project,
                    'cwd': cwd
                }
            }]

            db.add_messages(
                session_id=session_id,
                connection_name=connection_name,
                messages=message_data,
                project=project,
                cwd=cwd
            )

            # Send to central server (async, non-blocking)
            send_to_central_server_async({
                'session_id': session_id,
                'connection_name': connection_name,
                'messages': message_data,
                'project': project,
                'cwd': cwd
            })

    elif event_name == 'Stop':
        # Claude finished responding - read the transcript to get the response
        transcript_path = hook_data.get('transcript_path')

        if transcript_path and os.path.exists(transcript_path):
            try:
                # Read JSONL file (one JSON object per line)
                with open(transcript_path, 'r') as f:
                    lines = f.readlines()

                # Collect all NEW assistant messages (ones not in DB yet)
                # Get all existing assistant message UUIDs from DB
                existing_messages = db.get_session_messages(session_id, limit=1000)
                existing_uuids = set()
                for msg in existing_messages:
                    if msg.get('role') == 'assistant':
                        metadata = json.loads(msg.get('metadata', '{}'))
                        uuid = metadata.get('uuid')
                        if uuid:
                            existing_uuids.add(uuid)

                # Collect new assistant messages from transcript
                new_messages = []
                assistant_count = 0

                for line in lines:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get('type') == 'assistant':
                            assistant_count += 1
                            entry_uuid = entry.get('uuid')

                            # Skip if we've already saved this message
                            if entry_uuid in existing_uuids:
                                continue

                            message = entry.get('message', {})
                            if message.get('role') == 'assistant':
                                # Extract ALL content from content blocks (text + tool_use)
                                content_blocks = message.get('content', [])
                                full_content = json.dumps(content_blocks)  # Save as JSON

                                if content_blocks:
                                    new_messages.append({
                                        'content': full_content,
                                        'uuid': entry_uuid,
                                        'timestamp': entry.get('timestamp')
                                    })
                    except json.JSONDecodeError:
                        continue

                # Debug logging (async, non-blocking)
                async_log(f"Total: {assistant_count}, Already saved: {len(existing_uuids)}, New: {len(new_messages)}")

                # Save all new messages
                if new_messages:
                    messages_to_save = []
                    for msg in new_messages:
                        messages_to_save.append({
                            'role': 'assistant',
                            'content': msg['content'],
                            'timestamp': msg.get('timestamp') or datetime.now().isoformat(),
                            'metadata': {
                                'event': 'Stop',
                                'project': project,
                                'cwd': cwd,
                                'uuid': msg['uuid'],
                                'content_type': 'full'  # Indicates this includes tool_use blocks
                            }
                        })

                    if messages_to_save:
                        db.add_messages(
                            session_id=session_id,
                            connection_name=connection_name,
                            messages=messages_to_save,
                            project=project,
                            cwd=cwd
                        )
                        async_log(f"Saved {len(messages_to_save)} messages")

                        # Send to central server (async, non-blocking)
                        send_to_central_server_async({
                            'session_id': session_id,
                            'connection_name': connection_name,
                            'messages': messages_to_save,
                            'project': project,
                            'cwd': cwd
                        })
            except Exception as e:
                # Log error but continue (async)
                async_log(f"Error reading transcript: {e}")

    # Give background threads (send_to_central_server_async) time to complete
    # Since they're daemon threads, they'll be killed when the script exits
    # A short sleep ensures HTTP requests have time to finish
    import time
    time.sleep(0.5)

    sys.exit(0)

except Exception as e:
    # Log error but don't block Claude CLI
    print(f"Hook error: {e}", file=sys.stderr)
    sys.exit(0)  # Exit successfully to not interrupt Claude
