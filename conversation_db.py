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
                custom_title TEXT,
                project TEXT,
                cwd TEXT,
                message_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
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

        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_connection ON sessions(connection_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_modified ON sessions(last_modified)')
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
                if key in ['custom_title', 'project', 'cwd', 'message_count', 'metadata']:
                    update_fields.append(f"{key} = ?")
                    values.append(json.dumps(value) if key == 'metadata' else value)

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
                INSERT INTO sessions (session_id, connection_name, custom_title, project, cwd, message_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id,
                connection_name,
                kwargs.get('custom_title'),
                kwargs.get('project'),
                kwargs.get('cwd'),
                kwargs.get('message_count', 0),
                json.dumps(kwargs.get('metadata', {}))
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

        # Insert messages
        for msg in messages:
            cursor.execute('''
                INSERT INTO messages (conversation_id, session_id, message_id, role, content, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                conversation_id,
                session_id,
                msg.get('message_id'),
                msg.get('role', 'unknown'),
                msg.get('content', ''),
                msg.get('timestamp', datetime.now().isoformat()),
                json.dumps(msg.get('metadata', {}))
            ))

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
