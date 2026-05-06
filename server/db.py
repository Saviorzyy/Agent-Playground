"""Ember Protocol — SQLite Persistence"""
from __future__ import annotations
import sqlite3
import json
import os
import time
from typing import Optional

DB_PATH = None  # Set on init


def init_db(path: str):
    global DB_PATH
    DB_PATH = path
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            agent_name TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            chassis TEXT NOT NULL,
            created_at REAL DEFAULT (strftime('%s', 'now'))
        );
        CREATE TABLE IF NOT EXISTS world_snapshots (
            tick INTEGER PRIMARY KEY,
            timestamp REAL NOT NULL,
            snapshot_data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tick INTEGER NOT NULL,
            agent_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_data TEXT NOT NULL,
            result TEXT NOT NULL,
            timestamp REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_action_log_tick ON action_log(tick);
        CREATE INDEX IF NOT EXISTS idx_action_log_agent ON action_log(agent_id);
    """)
    conn.commit()
    conn.close()


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def register_agent(agent_id: str, agent_name: str, token_hash: str, chassis: dict):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO agents (agent_id, agent_name, token_hash, chassis) VALUES (?,?,?,?)",
                 (agent_id, agent_name, token_hash, json.dumps(chassis)))
    conn.commit()
    conn.close()


def verify_token(agent_id: str, token_hash: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT token_hash FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    conn.close()
    return row is not None and row[0] == token_hash


def save_snapshot(tick: int, snapshot_data: dict):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO world_snapshots (tick, timestamp, snapshot_data) VALUES (?,?,?)",
                 (tick, time.time(), json.dumps(snapshot_data)))
    conn.commit()
    conn.close()


def load_latest_snapshot() -> Optional[tuple[int, dict]]:
    conn = get_conn()
    row = conn.execute("SELECT tick, snapshot_data FROM world_snapshots ORDER BY tick DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return row[0], json.loads(row[1])
    return None


def log_action(tick: int, agent_id: str, action_type: str, action_data: dict, result: dict):
    conn = get_conn()
    conn.execute("INSERT INTO action_log (tick, agent_id, action_type, action_data, result, timestamp) VALUES (?,?,?,?,?,?)",
                 (tick, agent_id, action_type, json.dumps(action_data), json.dumps(result), time.time()))
    conn.commit()
    conn.close()
