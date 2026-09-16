"""SQLite data layer for the SE Account Manager.

Single embedded DB file, no server process. Schema is created on first
run. Add columns/tables here as you add features — SQLite migrations are
just `ALTER TABLE` calls guarded by a try/except in `_migrate()`.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get("SE_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "se_accounts.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

HEALTH_LEVELS = ["Healthy", "Attention", "At Risk"]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    ae_assigned TEXT,
    health TEXT DEFAULT 'Healthy',
    status_summary TEXT,
    last_call_date TEXT,
    last_call_summary TEXT,
    next_call_date TEXT,
    next_call_time TEXT,
    slack_channel_id TEXT,
    grafana_url TEXT,
    salesforce_url TEXT,
    slack_url TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deliverables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    due_date TEXT,
    status TEXT DEFAULT 'Open',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    due_date TEXT,
    status TEXT DEFAULT 'Open',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    note_date TEXT,
    summary TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS blockers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    link TEXT,
    status TEXT DEFAULT 'Open',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stakeholders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT,
    email TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------- accounts ----------

def list_accounts():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()


def get_account(account_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()


def create_account(name, ae_assigned=""):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO accounts (name, ae_assigned) VALUES (?, ?)", (name, ae_assigned)
        )
        return cur.lastrowid


def update_account(account_id, **fields):
    if not fields:
        return
    fields["updated_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE accounts SET {cols} WHERE id = ?", (*fields.values(), account_id))


def delete_account(account_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


# ---------- generic child-table helpers (deliverables, tasks, notes, blockers, stakeholders) ----------

def list_children(table, account_id, order_by="due_date"):
    with get_conn() as conn:
        try:
            return conn.execute(
                f"SELECT * FROM {table} WHERE account_id = ? ORDER BY {order_by} IS NULL, {order_by}",
                (account_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return conn.execute(
                f"SELECT * FROM {table} WHERE account_id = ? ORDER BY id DESC", (account_id,)
            ).fetchall()


def add_child(table, account_id, **fields):
    cols = ", ".join(["account_id", *fields.keys()])
    placeholders = ", ".join(["?"] * (len(fields) + 1))
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            (account_id, *fields.values()),
        )


def update_child(table, row_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE {table} SET {cols} WHERE id = ?", (*fields.values(), row_id))


def delete_child(table, row_id):
    with get_conn() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))


# ---------- rollup counts for the dashboard ----------

def open_counts(account_id):
    with get_conn() as conn:
        deliverables = conn.execute(
            "SELECT COUNT(*) FROM deliverables WHERE account_id = ? AND status != 'Done'", (account_id,)
        ).fetchone()[0]
        blockers = conn.execute(
            "SELECT COUNT(*) FROM blockers WHERE account_id = ? AND status != 'Resolved'", (account_id,)
        ).fetchone()[0]
        tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE account_id = ? AND status != 'Done'", (account_id,)
        ).fetchone()[0]
        return {"deliverables": deliverables, "blockers": blockers, "tasks": tasks}
