#!/usr/bin/env python3
"""
Claude Code Conversation Sync Service
Watches Claude Code transcript files and syncs them to central database
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime
import urllib.request
import urllib.error
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Add conversation_db to path
sys.path.insert(0, str(Path.home() / '.claude-bridge'))

from conversation_db import get_db

# Central server
CENTRAL_SERVER = os.environ.get('CLAUDE_CENTRAL_SERVER', 'http://100.94.187.56:8891')
CONNECTION_NAME = os.environ.get('CLAUDE_CONNECTION_NAME', 'Steel Server')

# Local database
db = get_db()

# Track which messages we've already synced per session
synced_messages = {}

def send_to_central_server(session_data):
    """Send session data to central server"""
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
        print(f"Failed to sync to central server: {e}", file=sys.stderr)
        return None

def sync_transcript(transcript_path):
    """Read and sync a transcript file"""
    session_id = Path(transcript_path).stem

    # Skip agent transcripts
    if session_id.startswith('agent-'):
        return

    try:
        # Get project directory from path
        # The folder name is the project path with / replaced by -
        # e.g., -opt-Claude-CLI-Cloud represents /opt/Claude-CLI-Cloud
        folder_name = Path(transcript_path).parent.name
        if folder_name.startswith('-'):
            cwd = '/' + folder_name[1:].replace('-', '/')
        else:
            cwd = folder_name
        project_dir = cwd

        # Read transcript file
        with open(transcript_path, 'r') as f:
            lines = f.readlines()

        # Initialize synced count for this session if needed
        if session_id not in synced_messages:
            # Check how many we already have in DB
            existing = db.get_session_messages(session_id, limit=10000)
            synced_messages[session_id] = len(existing)

        # Parse all messages
        all_messages = []
        for line in lines:
            try:
                entry = json.loads(line.strip())
                msg_type = entry.get('type')

                if msg_type == 'user':
                    # User message
                    message = entry.get('message', {})
                    content = message.get('content', '')
                    # Content is always an array in Claude Code
                    if isinstance(content, list):
                        content = json.dumps(content)
                    all_messages.append({
                        'role': 'user',
                        'content': content,
                        'timestamp': entry.get('timestamp'),
                        'uuid': entry.get('uuid')
                    })
                elif msg_type == 'assistant':
                    # Assistant message
                    message = entry.get('message', {})
                    if message.get('role') == 'assistant':
                        content_blocks = message.get('content', [])
                        all_messages.append({
                            'role': 'assistant',
                            'content': json.dumps(content_blocks),
                            'timestamp': entry.get('timestamp'),
                            'uuid': entry.get('uuid')
                        })
            except json.JSONDecodeError:
                continue

        # Only sync new messages
        new_messages = all_messages[synced_messages[session_id]:]

        if new_messages:
            # Format for database - ensure everything is properly serialized
            messages_to_save = []
            for msg in new_messages:
                # Ensure content is a string (should already be JSON string from parsing)
                content = msg['content']
                if not isinstance(content, str):
                    content = json.dumps(content)

                messages_to_save.append({
                    'role': str(msg['role']),
                    'content': content,
                    'timestamp': str(msg.get('timestamp') or datetime.now().isoformat()),
                    'metadata': json.dumps({
                        'event': 'ClaudeCodeSync',
                        'project': str(project_dir),
                        'cwd': str(cwd),
                        'uuid': str(msg.get('uuid', '')),
                        'content_type': 'full'
                    })
                })

            # Upsert session first
            db.upsert_session(
                session_id=session_id,
                connection_name=CONNECTION_NAME,
                project=project_dir,
                cwd=cwd
            )

            # Save to local DB
            try:
                # Debug: Check all message content types
                for i, msg in enumerate(messages_to_save):
                    if isinstance(msg.get('content'), list):
                        print(f"ERROR: Message {i} content is still a list!", file=sys.stderr)
                        print(f"Content: {msg['content'][:100]}", file=sys.stderr)
                    if isinstance(msg.get('metadata'), dict):
                        print(f"ERROR: Message {i} metadata is still a dict!", file=sys.stderr)

                db.add_messages(
                    session_id=session_id,
                    connection_name=CONNECTION_NAME,
                    messages=messages_to_save,
                    project=project_dir,
                    cwd=cwd
                )
            except Exception as e:
                print(f"DEBUG: Failed to add messages for {session_id[:8]}", file=sys.stderr)
                print(f"DEBUG: Error: {e}", file=sys.stderr)
                if messages_to_save:
                    print(f"DEBUG: First message keys: {messages_to_save[0].keys()}", file=sys.stderr)
                    for key, val in messages_to_save[0].items():
                        print(f"DEBUG:   {key}: {type(val).__name__}", file=sys.stderr)
                raise

            # Send to central server
            send_to_central_server({
                'session_id': session_id,
                'connection_name': CONNECTION_NAME,
                'messages': messages_to_save,
                'project': project_dir,
                'cwd': cwd
            })

            synced_messages[session_id] = len(all_messages)
            print(f"Synced {len(new_messages)} new messages for session {session_id[:8]}...", flush=True)

    except Exception as e:
        print(f"Error syncing transcript {transcript_path}: {e}", file=sys.stderr)

class TranscriptHandler(FileSystemEventHandler):
    """Handle transcript file changes"""

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.jsonl'):
            sync_transcript(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.jsonl'):
            sync_transcript(event.src_path)

def main():
    """Main sync loop"""
    print(f"Claude Code Sync Service starting...")
    print(f"Connection: {CONNECTION_NAME}")
    print(f"Central Server: {CENTRAL_SERVER}")

    # Watch directory
    watch_dir = Path.home() / '.claude' / 'projects'
    watch_dir.mkdir(parents=True, exist_ok=True)

    print(f"Watching: {watch_dir}")

    # Initial sync of all existing transcripts
    print("Performing initial sync of existing transcripts...")
    for transcript in watch_dir.glob('*/*.jsonl'):
        sync_transcript(str(transcript))

    # Start watching for changes
    event_handler = TranscriptHandler()
    observer = Observer()
    observer.schedule(event_handler, str(watch_dir), recursive=True)
    observer.start()

    print("Sync service running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nStopping sync service...")

    observer.join()

if __name__ == '__main__':
    main()
