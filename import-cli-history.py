#!/usr/bin/env python3
"""
Import existing Claude CLI session history into conversation database
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from conversation_db import get_db

def import_history_file(history_path: Path, connection_name: str = "claude-cli-imported"):
    """Import Claude CLI history.jsonl file with duplicate detection"""
    db = get_db()

    if not history_path.exists():
        print(f"History file not found: {history_path}")
        return 0, 0

    print(f"Importing from: {history_path}")

    imported = 0
    skipped = 0
    errors = 0

    # Build a set of existing messages to check for duplicates
    existing_messages = {}
    try:
        cursor = db.conn.cursor()
        cursor.execute('''
            SELECT session_id, content, timestamp
            FROM messages
            WHERE session_id LIKE 'claude-cli-%'
        ''')
        for row in cursor.fetchall():
            key = (row[0], row[1][:100], row[2][:10])  # session_id, first 100 chars of content, date part
            existing_messages[key] = True
    except Exception as e:
        print(f"Warning: Could not check for duplicates: {e}")

    with open(history_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            try:
                line = line.strip()
                if not line:
                    continue

                entry = json.loads(line)

                # Extract data
                content = entry.get('display', '')
                timestamp = entry.get('timestamp')
                project = entry.get('project', 'unknown')

                if not content:
                    continue

                # Convert timestamp from milliseconds to ISO format
                if timestamp:
                    dt = datetime.fromtimestamp(timestamp / 1000.0)
                    timestamp_iso = dt.isoformat()
                else:
                    timestamp_iso = datetime.now().isoformat()

                # Create session ID based on project and date
                session_date = timestamp_iso.split('T')[0] if timestamp else 'unknown'
                session_id = f"claude-cli-{project.replace('/', '-')}-{session_date}"

                # Check for duplicate
                check_key = (session_id, content[:100], timestamp_iso[:10])
                if check_key in existing_messages:
                    skipped += 1
                    continue

                # Upsert session
                db.upsert_session(
                    session_id=session_id,
                    connection_name=connection_name,
                    project=project,
                    cwd=project
                )

                # Add message
                db.add_messages(
                    session_id=session_id,
                    connection_name=connection_name,
                    messages=[{
                        'role': 'user',
                        'content': content,
                        'timestamp': timestamp_iso,
                        'metadata': {
                            'pasted_contents': entry.get('pastedContents', {}),
                            'imported_from': 'history.jsonl',
                            'original_line': line_num
                        }
                    }],
                    project=project,
                    cwd=project
                )

                # Add to existing set
                existing_messages[check_key] = True

                imported += 1

                if imported % 100 == 0:
                    print(f"Imported {imported} messages...")

            except json.JSONDecodeError as e:
                print(f"Error parsing line {line_num}: {e}")
                errors += 1
            except Exception as e:
                print(f"Error processing line {line_num}: {e}")
                errors += 1

    print(f"\n✓ Import complete!")
    print(f"  Imported: {imported} messages")
    print(f"  Skipped (duplicates): {skipped}")
    print(f"  Errors: {errors}")

    return imported, skipped

def main():
    # Default to ~/.claude/history.jsonl
    history_path = Path.home() / '.claude' / 'history.jsonl'

    # Allow custom path as argument
    if len(sys.argv) > 1:
        history_path = Path(sys.argv[1])

    print("Claude CLI History Import Tool")
    print("=" * 50)

    imported, skipped = import_history_file(history_path)

    if imported > 0:
        print("\nYou can now view these conversations in your web UI")
        print("They will appear under connection: 'claude-cli-imported'")

if __name__ == '__main__':
    main()
