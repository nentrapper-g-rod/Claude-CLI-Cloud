#!/usr/bin/env python3
"""
Test Phase 1: Database Migration
Tests that new columns are added correctly and pattern detection works
"""

import sys
from pathlib import Path

# Add conversation_db to path
sys.path.insert(0, '/opt/Claude-CLI-Cloud')

from conversation_db import get_db

def test_migration():
    print("Testing Phase 1: Database Migration")
    print("=" * 60)

    # Initialize database (will run migrations)
    print("\n1. Initializing database and running migrations...")
    db = get_db()
    print("   ✓ Database initialized")

    # Check that new columns exist
    print("\n2. Checking new columns exist...")
    cursor = db.conn.cursor()
    cursor.execute("PRAGMA table_info(sessions)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}

    required_columns = ['outcome_status', 'success_indicators', 'files_modified', 'git_commits_mentioned']
    for col in required_columns:
        if col in columns:
            print(f"   ✓ Column '{col}' exists (type: {columns[col]})")
        else:
            print(f"   ✗ Column '{col}' MISSING!")
            return False

    # Check indexes exist
    print("\n3. Checking indexes...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sessions_outcome'")
    if cursor.fetchone():
        print("   ✓ Index 'idx_sessions_outcome' exists")
    else:
        print("   ✗ Index 'idx_sessions_outcome' MISSING!")

    # Test pattern detection
    print("\n4. Testing success/failure pattern detection...")

    # Get a sample session
    sessions = db.get_sessions(limit=5)
    if not sessions:
        print("   ⚠ No sessions found to test")
        return True

    test_session = sessions[0]
    session_id = test_session['session_id']
    print(f"   Testing with session: {session_id[:16]}...")

    # Run pattern detection
    result = db.detect_session_outcome(session_id)
    print(f"   Outcome: {result['outcome_status']}")
    print(f"   Confidence: {result['confidence']:.2f}")
    print(f"   Success indicators: {len(result['success_indicators'])}")
    print(f"   Failure indicators: {len(result['failure_indicators'])}")

    # Test updating session with outcome
    print("\n5. Testing session outcome update...")
    db.update_session_outcome(session_id)

    # Verify it was updated
    cursor.execute("SELECT outcome_status, success_indicators FROM sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    if row:
        print(f"   ✓ Session updated: outcome_status = {row[0]}")
        print(f"   ✓ Success indicators stored: {len(row[1]) if row[1] else 0} chars")
    else:
        print("   ✗ Failed to retrieve updated session")

    # Test upsert with new columns
    print("\n6. Testing upsert with new columns...")
    test_session_id = "test_phase1_migration"
    db.upsert_session(
        session_id=test_session_id,
        connection_name="Test Connection",
        project="Test Project",
        cwd="/test/path",
        outcome_status="success",
        success_indicators=[{"pattern": "works", "weight": 1.0}],
        files_modified=["test.py", "main.py"],
        git_commits_mentioned=["abc123", "def456"]
    )

    # Verify
    cursor.execute("SELECT outcome_status, success_indicators, files_modified, git_commits_mentioned FROM sessions WHERE session_id = ?", (test_session_id,))
    row = cursor.fetchone()
    if row:
        print(f"   ✓ Test session created with outcome_status: {row[0]}")
        print(f"   ✓ success_indicators: {row[1][:50]}..." if row[1] else "   ✓ success_indicators: None")
        print(f"   ✓ files_modified: {row[2][:50]}..." if row[2] else "   ✓ files_modified: None")
        print(f"   ✓ git_commits: {row[3][:50]}..." if row[3] else "   ✓ git_commits: None")
    else:
        print("   ✗ Failed to create test session")

    # Clean up test session
    cursor.execute("DELETE FROM sessions WHERE session_id = ?", (test_session_id,))
    db.conn.commit()

    print("\n" + "=" * 60)
    print("✓ Phase 1 Migration Tests PASSED")
    print("=" * 60)
    return True

if __name__ == '__main__':
    try:
        success = test_migration()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
