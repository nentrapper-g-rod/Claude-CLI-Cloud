#!/usr/bin/env python3
"""
Backfill project tags for existing sessions based on directory matching
"""

import json
import sqlite3
from pathlib import Path
import re

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

def main():
    # Load custom projects
    custom_projects_path = Path.home() / '.claude' / 'custom_projects.json'
    if not custom_projects_path.exists():
        print("No custom_projects.json found")
        return

    with open(custom_projects_path, 'r') as f:
        custom_projects = json.load(f)

    print(f"Loaded {len(custom_projects)} projects")

    # Connect to database
    db_path = Path.home() / '.claude' / 'conversations.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all sessions
    cursor.execute('''
        SELECT id, session_id, cwd, project_tags
        FROM sessions
        WHERE cwd IS NOT NULL AND cwd != ''
    ''')

    sessions = cursor.fetchall()
    print(f"Found {len(sessions)} sessions to process")

    updated_count = 0
    for session_id_pk, session_id, cwd, existing_tags in sessions:
        # Match directory to projects
        project_tags = []
        for proj in custom_projects:
            proj_dirs = proj.get('directories', [])
            if proj.get('working_directory'):
                proj_dirs.append(proj['working_directory'])

            for proj_dir in proj_dirs:
                if paths_match(cwd, proj_dir):
                    project_tags.append({
                        'id': proj['id'],
                        'name': proj['name'],
                        'color': proj.get('color', '#4a9eff')
                    })
                    break

        # Update session with project tags (always update, even if empty, to ensure consistency)
        new_tags_json = json.dumps(project_tags)
        if existing_tags != new_tags_json:
            cursor.execute('''
                UPDATE sessions
                SET project_tags = ?
                WHERE id = ?
            ''', (new_tags_json, session_id_pk))
            updated_count += 1
            if project_tags:
                proj_names = ', '.join([t['name'] for t in project_tags])
                print(f"  Tagged session {session_id[:8]} ({cwd}) with: {proj_names}")
            else:
                print(f"  Cleared tags for session {session_id[:8]} ({cwd})")

    conn.commit()
    conn.close()

    print(f"\nBackfill complete! Updated {updated_count} sessions with project tags")

if __name__ == '__main__':
    main()
