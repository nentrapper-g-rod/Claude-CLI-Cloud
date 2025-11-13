#!/usr/bin/env python3
"""
Fix session timestamps - set last_modified to actual last message time
This fixes the issue where all sessions show "just now" because the hook
was updating last_modified on every event, even without new messages.
"""

import sys
from pathlib import Path
import sqlite3

# Database path
db_path = Path.home() / '.claude' / 'conversations.db'

print("Fixing session timestamps...")
print("=" * 60)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get all sessions
cursor.execute('SELECT session_id FROM sessions')
sessions = cursor.fetchall()

print(f"Found {len(sessions)} sessions to process")

fixed_count = 0
no_messages_count = 0

for session in sessions:
    session_id = session['session_id']

    # Get the actual last message timestamp for this session
    cursor.execute('''
        SELECT MAX(timestamp) as last_message_time
        FROM messages
        WHERE session_id = ?
    ''', (session_id,))

    result = cursor.fetchone()
    last_message_time = result['last_message_time'] if result else None

    if last_message_time:
        # Update session's last_modified to match the actual last message time
        cursor.execute('''
            UPDATE sessions
            SET last_modified = ?
            WHERE session_id = ?
        ''', (last_message_time, session_id))
        fixed_count += 1
    else:
        # No messages yet - leave last_modified as created_at
        cursor.execute('''
            UPDATE sessions
            SET last_modified = created_at
            WHERE session_id = ?
        ''', (session_id,))
        no_messages_count += 1

conn.commit()

print(f"\n✓ Fixed {fixed_count} sessions with messages")
print(f"✓ Reset {no_messages_count} sessions with no messages to created_at")
print("=" * 60)
print("Session timestamps have been corrected!")

conn.close()
