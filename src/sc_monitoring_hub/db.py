import sqlite3
import json
import time
import socket
from pathlib import Path
from typing import List, Dict, Any, Optional
from sc_monitoring_hub.config import DB_PATH

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

def init_db():
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS systems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            host TEXT NOT NULL,
            port INTEGER NOT NULL DEFAULT 22,
            username TEXT,
            auth_type TEXT DEFAULT 'password', -- 'password', 'key_file', 'key_content'
            auth_credential TEXT,
            is_local INTEGER DEFAULT 0,
            mode TEXT DEFAULT 'agentless', -- 'local', 'agentless', 'agent'
            agent_port INTEGER DEFAULT 9990,
            agent_token TEXT,
            status TEXT DEFAULT 'online', -- 'online', 'offline', 'error', 'installing'
            status_message TEXT,
            last_seen REAL,
            created_at REAL NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS metrics_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            cpu_percent REAL,
            memory_percent REAL,
            memory_used_bytes INTEGER,
            memory_total_bytes INTEGER,
            disk_percent REAL,
            disk_used_bytes INTEGER,
            disk_total_bytes INTEGER,
            swap_percent REAL,
            net_bytes_sent INTEGER,
            net_bytes_recv INTEGER,
            uptime_seconds REAL,
            load_avg TEXT,
            raw_json TEXT,
            FOREIGN KEY (system_id) REFERENCES systems (id) ON DELETE CASCADE
        )
        """)

        cursor.execute("SELECT COUNT(*) FROM systems WHERE is_local = 1")
        if cursor.fetchone()[0] == 0:
            hostname = socket.gethostname()
            cursor.execute("""
                INSERT INTO systems (name, host, port, username, is_local, mode, status, created_at)
                VALUES (?, '127.0.0.1', 0, 'local', 1, 'local', 'online', ?)
            """, (f"Local Host ({hostname})", time.time()))
        conn.commit()
    finally:
        conn.close()

def list_systems() -> List[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM systems ORDER BY is_local DESC, id ASC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_system(system_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM systems WHERE id = ?", (system_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def add_system(
    name: str,
    host: str,
    port: int = 22,
    username: str = "root",
    auth_type: str = "password",
    auth_credential: str = "",
    mode: str = "agentless",
    agent_port: int = 9990
) -> int:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO systems (name, host, port, username, auth_type, auth_credential, is_local, mode, agent_port, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 'offline', ?)
        """, (name, host, port, username, auth_type, auth_credential, mode, agent_port, time.time()))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def update_system_status(system_id: int, status: str, message: str = ""):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE systems
            SET status = ?, status_message = ?, last_seen = ?
            WHERE id = ?
        """, (status, message, time.time(), system_id))
        conn.commit()
    finally:
        conn.close()

def update_system_mode(system_id: int, mode: str):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE systems SET mode = ? WHERE id = ?", (mode, system_id))
        conn.commit()
    finally:
        conn.close()

def delete_system(system_id: int):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM systems WHERE id = ? AND is_local = 0", (system_id,))
        conn.commit()
    finally:
        conn.close()

def save_metrics(system_id: int, metrics: Dict[str, Any]):
    conn = get_db()
    try:
        cursor = conn.cursor()
        now = time.time()
        load_avg_str = json.dumps(metrics.get("load_avg", []))
        cursor.execute("""
            INSERT INTO metrics_history (
                system_id, timestamp, cpu_percent, memory_percent, memory_used_bytes, memory_total_bytes,
                disk_percent, disk_used_bytes, disk_total_bytes, swap_percent, net_bytes_sent, net_bytes_recv,
                uptime_seconds, load_avg, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            system_id, now,
            metrics.get("cpu_percent", 0.0),
            metrics.get("memory_percent", 0.0),
            metrics.get("memory_used_bytes", 0),
            metrics.get("memory_total_bytes", 0),
            metrics.get("disk_percent", 0.0),
            metrics.get("disk_used_bytes", 0),
            metrics.get("disk_total_bytes", 0),
            metrics.get("swap_percent", 0.0),
            metrics.get("net_bytes_sent", 0),
            metrics.get("net_bytes_recv", 0),
            metrics.get("uptime_seconds", 0.0),
            load_avg_str,
            json.dumps(metrics)
        ))
        # Keep last 500 records per system to keep database lightweight
        cursor.execute("""
            DELETE FROM metrics_history
            WHERE system_id = ? AND id NOT IN (
                SELECT id FROM metrics_history WHERE system_id = ? ORDER BY id DESC LIMIT 500
            )
        """, (system_id, system_id))
        conn.commit()
    finally:
        conn.close()

def get_latest_metrics(system_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT raw_json FROM metrics_history
            WHERE system_id = ?
            ORDER BY id DESC LIMIT 1
        """, (system_id,))
        row = cursor.fetchone()
        if row and row["raw_json"]:
            return json.loads(row["raw_json"])
        return None
    finally:
        conn.close()

def get_metrics_history(system_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, cpu_percent, memory_percent, disk_percent, swap_percent, net_bytes_sent, net_bytes_recv
            FROM metrics_history
            WHERE system_id = ?
            ORDER BY id DESC LIMIT ?
        """, (system_id, limit))
        rows = cursor.fetchall()
        return [dict(row) for row in reversed(rows)]
    finally:
        conn.close()
