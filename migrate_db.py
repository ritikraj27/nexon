#!/usr/bin/env python3
# migrate_db.py
# ============================================================
# NEXON Database Migration Script
# Run this ONCE to add new columns to existing nexon.db
# without losing any existing chat history.
#
# Usage:
#   cd /Users/ritikraj/Desktop/nexon
#   python migrate_db.py
# ============================================================

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nexon.db")

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"[migrate] nexon.db not found at {DB_PATH}")
        print("[migrate] It will be created fresh on first server start. No migration needed.")
        return

    print(f"[migrate] Found database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # ── Helper ────────────────────────────────────────────────
    def column_exists(table, column):
        cur.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in cur.fetchall()]
        return column in cols

    def table_exists(table):
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return cur.fetchone() is not None

    def add_column(table, column, col_type, default=None):
        if not column_exists(table, column):
            default_clause = f" DEFAULT {default}" if default is not None else ""
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}"
            cur.execute(sql)
            print(f"  ✅ Added column: {table}.{column}")
        else:
            print(f"  ⏭  Already exists: {table}.{column}")

    def create_table_if_missing(name, create_sql):
        if not table_exists(name):
            cur.execute(create_sql)
            print(f"  ✅ Created table: {name}")
        else:
            print(f"  ⏭  Table exists: {name}")

    print("\n[migrate] Migrating messages table...")
    if table_exists("messages"):
        add_column("messages", "voice_stress",   "INTEGER", 0)
        add_column("messages", "voice_emotion",  "TEXT",    "''")
        add_column("messages", "parallel_tasks", "TEXT",    "NULL")

    print("\n[migrate] Creating new tables if missing...")

    # memory_nodes
    create_table_if_missing("memory_nodes", """
        CREATE TABLE memory_nodes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            content       TEXT NOT NULL,
            memory_type   TEXT DEFAULT 'fact',
            tags          TEXT DEFAULT '[]',
            session_id    INTEGER,
            importance    REAL DEFAULT 0.5,
            source        TEXT DEFAULT 'user',
            embedding     TEXT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_accessed DATETIME DEFAULT CURRENT_TIMESTAMP,
            access_count  INTEGER DEFAULT 0
        )
    """)

    # memory_edges
    create_table_if_missing("memory_edges", """
        CREATE TABLE memory_edges (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            from_node_id INTEGER NOT NULL,
            to_node_id   INTEGER NOT NULL,
            weight       REAL DEFAULT 0.5,
            edge_type    TEXT DEFAULT 'similar',
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (from_node_id) REFERENCES memory_nodes(id),
            FOREIGN KEY (to_node_id)   REFERENCES memory_nodes(id)
        )
    """)

    # usage_patterns
    create_table_if_missing("usage_patterns", """
        CREATE TABLE usage_patterns (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_key   TEXT UNIQUE NOT NULL,
            intent        TEXT NOT NULL,
            params_sample TEXT DEFAULT '{}',
            emotion       TEXT DEFAULT 'neutral',
            day_of_week   TEXT DEFAULT '',
            hour_of_day   INTEGER DEFAULT 0,
            count         INTEGER DEFAULT 1,
            success_count INTEGER DEFAULT 0,
            first_seen    DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # personality_profiles
    create_table_if_missing("personality_profiles", """
        CREATE TABLE personality_profiles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT UNIQUE NOT NULL,
            profile_json TEXT DEFAULT '{}',
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # gesture_macros
    create_table_if_missing("gesture_macros", """
        CREATE TABLE gesture_macros (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            gesture_name TEXT NOT NULL,
            macro_name   TEXT NOT NULL,
            commands     TEXT DEFAULT '[]',
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            run_count    INTEGER DEFAULT 0,
            last_run     DATETIME,
            is_active    INTEGER DEFAULT 1
        )
    """)

    # voice_analysis
    create_table_if_missing("voice_analysis", """
        CREATE TABLE voice_analysis (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id    INTEGER,
            session_id    INTEGER,
            stress_level  INTEGER DEFAULT 0,
            confidence    INTEGER DEFAULT 50,
            energy_level  TEXT DEFAULT 'normal',
            speech_rate   TEXT DEFAULT 'normal',
            voice_emotion TEXT DEFAULT 'neutral',
            pitch_variance REAL DEFAULT 0.0,
            details_json  TEXT DEFAULT '{}',
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # preferences (ensure exists)
    create_table_if_missing("preferences", """
        CREATE TABLE preferences (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            key   TEXT UNIQUE NOT NULL,
            value TEXT DEFAULT ''
        )
    """)

    # clipboard (ensure exists)
    create_table_if_missing("clipboard", """
        CREATE TABLE clipboard (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            content      TEXT NOT NULL,
            content_type TEXT DEFAULT 'text',
            timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP,
            pinned       INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()

    print("\n✅ Migration complete! All columns and tables are up to date.")
    print("   You can now start the server: uvicorn backend.main:app --reload")

if __name__ == "__main__":
    migrate()