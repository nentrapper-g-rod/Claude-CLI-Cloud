#!/usr/bin/env python3
"""
Conversation Database Manager
Handles SQLite database for centralized conversation storage
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import os

class ConversationDB:
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Default to ~/.claude/conversations.db
            claude_home = Path.home() / '.claude'
            claude_home.mkdir(parents=True, exist_ok=True)
            db_path = claude_home / 'conversations.db'

        self.db_path = str(db_path)
        self.conn = None
        self._init_db()

        # Optimize for performance
        self._optimize_db()

    def _init_db(self):
        """Initialize database with schema"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        cursor = self.conn.cursor()

        # Create sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                connection_name TEXT NOT NULL,
                parent_session_id TEXT,
                custom_title TEXT,
                project TEXT,
                cwd TEXT,
                message_count INTEGER DEFAULT 0,
                is_favorite INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (parent_session_id) REFERENCES sessions(session_id)
            )
        ''')

        # Create conversations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                connection_name TEXT NOT NULL,
                project TEXT,
                cwd TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        ''')

        # Create messages table with full-text search
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                message_id TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        ''')

        # Create full-text search virtual table
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                role,
                session_id,
                content=messages,
                content_rowid=id
            )
        ''')

        # Migration: Add parent_session_id column if it doesn't exist (before creating indexes)
        try:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'parent_session_id' not in columns:
                cursor.execute('ALTER TABLE sessions ADD COLUMN parent_session_id TEXT')
                self.conn.commit()
        except sqlite3.OperationalError as e:
            # Column might already exist or database might be locked
            # Verify column exists before raising error
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'parent_session_id' not in columns:
                raise  # Re-raise only if column still doesn't exist

        # Migration: Add is_favorite column if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'is_favorite' not in columns:
                cursor.execute('ALTER TABLE sessions ADD COLUMN is_favorite INTEGER DEFAULT 0')
                self.conn.commit()
        except sqlite3.OperationalError as e:
            # Column might already exist or database might be locked
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'is_favorite' not in columns:
                raise  # Re-raise only if column still doesn't exist

        # Migration: Add project_tags column if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'project_tags' not in columns:
                cursor.execute('ALTER TABLE sessions ADD COLUMN project_tags TEXT')
                self.conn.commit()
        except sqlite3.OperationalError as e:
            # Column might already exist or database might be locked
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'project_tags' not in columns:
                raise  # Re-raise only if column still doesn't exist

        # Migration: Add outcome_status column if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'outcome_status' not in columns:
                cursor.execute("ALTER TABLE sessions ADD COLUMN outcome_status TEXT CHECK(outcome_status IN ('success', 'failure', 'unclear', 'in_progress'))")
                self.conn.commit()
        except sqlite3.OperationalError as e:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'outcome_status' not in columns:
                raise

        # Migration: Add success_indicators column if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'success_indicators' not in columns:
                cursor.execute('ALTER TABLE sessions ADD COLUMN success_indicators TEXT')
                self.conn.commit()
        except sqlite3.OperationalError as e:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'success_indicators' not in columns:
                raise

        # Migration: Add files_modified column if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'files_modified' not in columns:
                cursor.execute('ALTER TABLE sessions ADD COLUMN files_modified TEXT')
                self.conn.commit()
        except sqlite3.OperationalError as e:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'files_modified' not in columns:
                raise

        # Migration: Add git_commits_mentioned column if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'git_commits_mentioned' not in columns:
                cursor.execute('ALTER TABLE sessions ADD COLUMN git_commits_mentioned TEXT')
                self.conn.commit()
        except sqlite3.OperationalError as e:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'git_commits_mentioned' not in columns:
                raise

        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_connection ON sessions(connection_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_modified ON sessions(last_modified)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_favorite ON sessions(is_favorite)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_outcome ON sessions(outcome_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)')

        # Create triggers to keep FTS in sync
        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content, role, session_id)
                VALUES (new.id, new.content, new.role, new.session_id);
            END
        ''')

        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                DELETE FROM messages_fts WHERE rowid = old.id;
            END
        ''')

        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                DELETE FROM messages_fts WHERE rowid = old.id;
                INSERT INTO messages_fts(rowid, content, role, session_id)
                VALUES (new.id, new.content, new.role, new.session_id);
            END
        ''')

        self.conn.commit()

    def _optimize_db(self):
        """Optimize database for performance"""
        cursor = self.conn.cursor()

        # Set performance-optimized PRAGMA settings
        cursor.execute('PRAGMA journal_mode = WAL')  # Write-Ahead Logging for better concurrency
        cursor.execute('PRAGMA synchronous = NORMAL')  # Faster writes, still safe
        cursor.execute('PRAGMA cache_size = -64000')  # 64MB cache
        cursor.execute('PRAGMA temp_store = MEMORY')  # Use memory for temp storage
        cursor.execute('PRAGMA mmap_size = 30000000000')  # Memory-mapped I/O

        self.conn.commit()

    def upsert_session(self, session_id: str, connection_name: str, **kwargs):
        """Insert or update a session"""
        cursor = self.conn.cursor()

        # Check if session exists
        cursor.execute('SELECT id FROM sessions WHERE session_id = ?', (session_id,))
        exists = cursor.fetchone()

        if exists:
            # Update existing session
            update_fields = []
            values = []
            for key, value in kwargs.items():
                if key in ['parent_session_id', 'custom_title', 'project', 'cwd', 'message_count', 'is_favorite', 'project_tags', 'metadata', 'outcome_status', 'success_indicators', 'files_modified', 'git_commits_mentioned']:
                    update_fields.append(f"{key} = ?")
                    values.append(json.dumps(value) if key in ['metadata', 'project_tags', 'success_indicators', 'files_modified', 'git_commits_mentioned'] else value)

            if update_fields:
                update_fields.append("last_modified = CURRENT_TIMESTAMP")
                values.append(session_id)
                cursor.execute(
                    f"UPDATE sessions SET {', '.join(update_fields)} WHERE session_id = ?",
                    values
                )
        else:
            # Insert new session
            cursor.execute('''
                INSERT INTO sessions (session_id, connection_name, parent_session_id, custom_title, project, cwd, message_count, is_favorite, project_tags, metadata, outcome_status, success_indicators, files_modified, git_commits_mentioned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id,
                connection_name,
                kwargs.get('parent_session_id'),
                kwargs.get('custom_title'),
                kwargs.get('project'),
                kwargs.get('cwd'),
                kwargs.get('message_count', 0),
                kwargs.get('is_favorite', 0),
                json.dumps(kwargs.get('project_tags', [])),
                json.dumps(kwargs.get('metadata', {})),
                kwargs.get('outcome_status'),
                json.dumps(kwargs.get('success_indicators', [])),
                json.dumps(kwargs.get('files_modified', [])),
                json.dumps(kwargs.get('git_commits_mentioned', []))
            ))

        self.conn.commit()

    def add_messages(self, session_id: str, connection_name: str, messages: List[Dict],
                    project: str = None, cwd: str = None):
        """Add messages to a conversation"""
        cursor = self.conn.cursor()

        # Get existing conversation or create new one (one conversation per session)
        cursor.execute('''
            SELECT id FROM conversations
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        ''', (session_id,))

        row = cursor.fetchone()
        if row:
            conversation_id = row[0]
        else:
            # Create new conversation for this session
            cursor.execute('''
                INSERT INTO conversations (session_id, connection_name, project, cwd)
                VALUES (?, ?, ?, ?)
            ''', (session_id, connection_name, project, cwd))
            conversation_id = cursor.lastrowid

        # Insert messages (skip duplicates based on message_id or timestamp+content)
        for msg in messages:
            message_id = msg.get('message_id')
            timestamp = msg.get('timestamp', datetime.now().isoformat())
            content = msg.get('content', '')
            role = msg.get('role', 'unknown')

            # Check if message already exists
            if message_id:
                cursor.execute('''
                    SELECT id FROM messages
                    WHERE session_id = ? AND message_id = ?
                ''', (session_id, message_id))

                if cursor.fetchone():
                    # Message already exists, skip it
                    continue
            else:
                # No message_id, check by timestamp and content
                cursor.execute('''
                    SELECT id FROM messages
                    WHERE session_id = ? AND timestamp = ? AND content = ? AND role = ?
                ''', (session_id, timestamp, content, role))

                if cursor.fetchone():
                    # Message already exists, skip it
                    continue

            try:
                cursor.execute('''
                    INSERT INTO messages (conversation_id, session_id, message_id, role, content, timestamp, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    conversation_id,
                    session_id,
                    message_id,
                    role,
                    content,
                    timestamp,
                    json.dumps(msg.get('metadata', {}))
                ))
            except sqlite3.IntegrityError:
                # Duplicate message (caught by unique constraint), skip it
                continue

        # Update session message count
        cursor.execute('''
            UPDATE sessions
            SET message_count = (SELECT COUNT(*) FROM messages WHERE session_id = ?),
                last_modified = CURRENT_TIMESTAMP
            WHERE session_id = ?
        ''', (session_id, session_id))

        self.conn.commit()

    def search_messages(self, query: str, connection_name: str = None,
                       session_id: str = None, limit: int = 100) -> List[Dict]:
        """Full-text search across messages"""
        cursor = self.conn.cursor()

        sql = '''
            SELECT m.*, s.connection_name, s.custom_title, s.project, s.cwd
            FROM messages m
            JOIN sessions s ON m.session_id = s.session_id
            WHERE m.id IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?)
        '''
        params = [query]

        if connection_name:
            sql += ' AND s.connection_name = ?'
            params.append(connection_name)

        if session_id:
            sql += ' AND m.session_id = ?'
            params.append(session_id)

        sql += ' ORDER BY m.timestamp DESC LIMIT ?'
        params.append(limit)

        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_session_messages(self, session_id: str, limit: int = 1000) -> List[Dict]:
        """Get all messages for a session"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY timestamp ASC
            LIMIT ?
        ''', (session_id, limit))
        return [dict(row) for row in cursor.fetchall()]

    def get_sessions(self, connection_name: str = None, limit: int = 100) -> List[Dict]:
        """Get sessions, optionally filtered by connection"""
        cursor = self.conn.cursor()

        if connection_name:
            cursor.execute('''
                SELECT * FROM sessions
                WHERE connection_name = ?
                ORDER BY last_modified DESC
                LIMIT ?
            ''', (connection_name, limit))
        else:
            cursor.execute('''
                SELECT * FROM sessions
                ORDER BY last_modified DESC
                LIMIT ?
            ''', (limit,))

        return [dict(row) for row in cursor.fetchall()]

    def get_connections(self) -> List[str]:
        """Get list of all connection names"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT connection_name FROM sessions ORDER BY connection_name')
        return [row[0] for row in cursor.fetchall()]

    def get_sessions_grouped(self, limit: int = 1000) -> Dict[str, Dict[str, List[Dict]]]:
        """Get sessions grouped by connection and directory, sorted by recency"""
        cursor = self.conn.cursor()

        # Get all sessions with their latest message timestamp
        cursor.execute('''
            SELECT s.*, MAX(m.timestamp) as latest_message
            FROM sessions s
            LEFT JOIN messages m ON s.session_id = m.session_id
            GROUP BY s.session_id
            ORDER BY latest_message DESC
            LIMIT ?
        ''', (limit,))

        sessions = [dict(row) for row in cursor.fetchall()]

        # Group by connection, then by directory (cwd)
        grouped = {}
        for session in sessions:
            connection = session.get('connection_name', 'Unknown')
            directory = session.get('cwd', 'Unknown')

            if connection not in grouped:
                grouped[connection] = {}

            if directory not in grouped[connection]:
                grouped[connection][directory] = []

            grouped[connection][directory].append(session)

        return grouped

    def get_session_thread(self, session_id: str) -> List[Dict]:
        """Get the full thread (parent chain) for a session, ordered from root to current"""
        cursor = self.conn.cursor()
        thread = []
        current_id = session_id
        seen_ids = set()

        # Walk up the parent chain
        while current_id and current_id not in seen_ids:
            seen_ids.add(current_id)
            cursor.execute('SELECT * FROM sessions WHERE session_id = ?', (current_id,))
            session = cursor.fetchone()

            if session:
                thread.append(dict(session))
                current_id = session['parent_session_id']
            else:
                break

        # Reverse to get root -> current order
        return list(reversed(thread))

    def get_session_children(self, session_id: str) -> List[Dict]:
        """Get direct children of a session"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM sessions
            WHERE parent_session_id = ?
            ORDER BY created_at ASC
        ''', (session_id,))
        return [dict(row) for row in cursor.fetchall()]

    def get_session_tree(self, session_id: str) -> Dict:
        """Get the complete tree of a session (parent chain + all descendants)"""
        # Get the root of this thread
        thread = self.get_session_thread(session_id)
        root_id = thread[0]['session_id'] if thread else session_id

        # Build tree recursively from root
        def build_tree(sid: str) -> Dict:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM sessions WHERE session_id = ?', (sid,))
            session = cursor.fetchone()

            if not session:
                return None

            result = dict(session)
            children = self.get_session_children(sid)
            if children:
                result['children'] = [build_tree(child['session_id']) for child in children]

            return result

        return build_tree(root_id)

    def get_root_sessions(self, connection_name: str = None, limit: int = 100) -> List[Dict]:
        """Get only root sessions (sessions with no parent), sorted by recency"""
        cursor = self.conn.cursor()

        sql = '''
            SELECT s.*, MAX(m.timestamp) as latest_message
            FROM sessions s
            LEFT JOIN messages m ON s.session_id = m.session_id
            WHERE s.parent_session_id IS NULL
        '''
        params = []

        if connection_name:
            sql += ' AND s.connection_name = ?'
            params.append(connection_name)

        sql += '''
            GROUP BY s.session_id
            ORDER BY latest_message DESC
            LIMIT ?
        '''
        params.append(limit)

        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_favorite_sessions(self, connection_name: str = None, limit: int = 100) -> List[Dict]:
        """Get favorite/pinned sessions, sorted by recency"""
        cursor = self.conn.cursor()

        sql = '''
            SELECT s.*, MAX(m.timestamp) as latest_message
            FROM sessions s
            LEFT JOIN messages m ON s.session_id = m.session_id
            WHERE s.is_favorite = 1
        '''
        params = []

        if connection_name:
            sql += ' AND s.connection_name = ?'
            params.append(connection_name)

        sql += '''
            GROUP BY s.session_id
            ORDER BY latest_message DESC
            LIMIT ?
        '''
        params.append(limit)

        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def toggle_favorite(self, session_id: str) -> bool:
        """Toggle favorite status of a session. Returns new favorite status."""
        cursor = self.conn.cursor()

        # Get current status
        cursor.execute('SELECT is_favorite FROM sessions WHERE session_id = ?', (session_id,))
        row = cursor.fetchone()

        if row:
            # Session exists - toggle its favorite status
            current_status = row[0]
            new_status = 0 if current_status else 1

            cursor.execute(
                'UPDATE sessions SET is_favorite = ? WHERE session_id = ?',
                (new_status, session_id)
            )
            self.conn.commit()
            return bool(new_status)
        else:
            # Session doesn't exist yet - create it with is_favorite=1
            cursor.execute(
                'INSERT INTO sessions (session_id, is_favorite, created_at, last_activity) VALUES (?, 1, datetime("now"), datetime("now"))',
                (session_id,)
            )
            self.conn.commit()
            return True

    def detect_session_outcome(self, session_id: str) -> Dict[str, Any]:
        """
        Analyze a session's messages to detect success/failure indicators
        Returns: {
            'outcome_status': 'success' | 'failure' | 'unclear' | 'in_progress',
            'success_indicators': [...],
            'failure_indicators': [...],
            'confidence': 0.0-1.0
        }
        """
        messages = self.get_session_messages(session_id)

        # Success patterns
        success_patterns = [
            'works', 'working', 'perfect', 'great', 'excellent', 'good', 'thanks',
            'looks good', 'that works', 'working now', 'fixed', 'solved',
            'test passed', 'tests passed', 'build successful', 'deployed',
            '✓', '✔', '👍', 'success', 'completed', 'done'
        ]

        # Failure patterns
        failure_patterns = [
            'error', 'failed', 'failure', 'broken', 'not working', 'doesnt work',
            "doesn't work", 'issue', 'problem', 'bug', 'crash', 'exception',
            'wrong', 'incorrect', 'still not', 'still broken', 'try again',
            '❌', '✗', 'test failed', 'tests failed', 'build failed'
        ]

        success_indicators = []
        failure_indicators = []

        # Analyze messages (give more weight to later messages)
        for idx, msg in enumerate(messages):
            content = msg.get('content', '').lower()
            role = msg.get('role', '')

            # Check for success patterns
            for pattern in success_patterns:
                if pattern in content:
                    weight = 1.0 + (idx / len(messages)) * 0.5  # Later messages have higher weight
                    success_indicators.append({
                        'pattern': pattern,
                        'message': content[:100],
                        'role': role,
                        'weight': weight
                    })

            # Check for failure patterns
            for pattern in failure_patterns:
                if pattern in content:
                    weight = 1.0 + (idx / len(messages)) * 0.5
                    failure_indicators.append({
                        'pattern': pattern,
                        'message': content[:100],
                        'role': role,
                        'weight': weight
                    })

        # Calculate scores
        success_score = sum(ind['weight'] for ind in success_indicators)
        failure_score = sum(ind['weight'] for ind in failure_indicators)

        # Determine outcome
        if success_score == 0 and failure_score == 0:
            outcome_status = 'unclear'
            confidence = 0.0
        elif success_score > failure_score * 1.5:  # Success clearly outweighs failure
            outcome_status = 'success'
            confidence = min(1.0, success_score / (success_score + failure_score))
        elif failure_score > success_score * 1.5:  # Failure clearly outweighs success
            outcome_status = 'failure'
            confidence = min(1.0, failure_score / (success_score + failure_score))
        else:
            outcome_status = 'in_progress'  # Mixed signals
            confidence = 0.5

        return {
            'outcome_status': outcome_status,
            'success_indicators': success_indicators,
            'failure_indicators': failure_indicators,
            'confidence': confidence,
            'success_score': success_score,
            'failure_score': failure_score
        }

    def update_session_outcome(self, session_id: str):
        """Analyze session and update outcome_status and success_indicators"""
        result = self.detect_session_outcome(session_id)

        # Only update if we have reasonable confidence
        if result['confidence'] >= 0.3:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE sessions
                SET outcome_status = ?,
                    success_indicators = ?
                WHERE session_id = ?
            ''', (
                result['outcome_status'],
                json.dumps({
                    'success': result['success_indicators'],
                    'failure': result['failure_indicators'],
                    'confidence': result['confidence']
                }),
                session_id
            ))
            self.conn.commit()

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

# Singleton instance
_db_instance = None

def get_db() -> ConversationDB:
    """Get singleton database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = ConversationDB()
    return _db_instance
