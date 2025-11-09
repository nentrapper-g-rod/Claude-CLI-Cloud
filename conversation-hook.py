#!/usr/bin/env python3
"""
Claude CLI Hook for Conversation Logging
Captures user prompts and assistant responses and saves to database
Also sends to central server for aggregation
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
import urllib.request
import urllib.error

# Add the path to conversation_db module
sys.path.insert(0, str(Path.home() / '.claude-bridge'))

# Central server for conversation aggregation
CENTRAL_SERVER = os.environ.get('CLAUDE_CENTRAL_SERVER', 'http://100.94.187.56:8891')

def send_to_central_server(session_data):
    """Send session data to central server for aggregation"""
    try:
        data = json.dumps(session_data).encode('utf-8')
        req = urllib.request.Request(
            f'{CENTRAL_SERVER}/api/conversations/sync',
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.read()
    except Exception as e:
        # Log but don't fail - local DB is primary
        debug_log = Path.home() / '.claude-bridge' / 'hook-debug.log'
        with open(debug_log, 'a') as f:
            f.write(f"[{datetime.now().isoformat()}] Failed to send to central server: {e}\n")
        return None

try:
    from conversation_db import get_db

    # Read hook data from stdin
    hook_data = json.load(sys.stdin)

    # Debug logging
    debug_log = Path.home() / '.claude-bridge' / 'hook-debug.log'
    with open(debug_log, 'a') as f:
        f.write(f"\n[{datetime.now().isoformat()}] Hook event: {hook_data.get('hook_event_name')}\n")
        f.write(f"Hook data: {json.dumps(hook_data, indent=2)}\n")

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
        connection_name = hostname_map.get(hostname.lower(), f"{hostname} (Local CLI)")

    db = get_db()

    # Ensure session exists
    db.upsert_session(
        session_id=session_id,
        connection_name=connection_name,
        project=project,
        cwd=cwd
    )

    # Send session info to central server
    send_to_central_server({
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

            # Send to central server
            send_to_central_server({
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

                # Debug logging
                with open(debug_log, 'a') as f:
                    f.write(f"Total assistant messages in transcript: {assistant_count}\n")
                    f.write(f"Already saved: {len(existing_uuids)}\n")
                    f.write(f"New messages to save: {len(new_messages)}\n")
                    if new_messages:
                        f.write(f"First new message UUID: {new_messages[0].get('uuid')}\n")

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
                        with open(debug_log, 'a') as f:
                            f.write(f"Successfully saved {len(messages_to_save)} messages\n")

                        # Send to central server
                        send_to_central_server({
                            'session_id': session_id,
                            'connection_name': connection_name,
                            'messages': messages_to_save,
                            'project': project,
                            'cwd': cwd
                        })
            except Exception as e:
                # Log error but continue
                with open(debug_log, 'a') as f:
                    f.write(f"Error reading transcript: {e}\n")
                print(f"Error reading transcript: {e}", file=sys.stderr)

        # Update session timestamp
        db.upsert_session(
            session_id=session_id,
            connection_name=connection_name
        )

    sys.exit(0)

except Exception as e:
    # Log error but don't block Claude CLI
    print(f"Hook error: {e}", file=sys.stderr)
    sys.exit(0)  # Exit successfully to not interrupt Claude
