"""SQLite data layer for the SE Account Manager.

Single embedded DB file, no server process. Schema is created on first
run. Add columns/tables here as you add features — SQLite migrations are
just `ALTER TABLE` calls guarded by a try/except in `_migrate()`.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

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
    se_assigned TEXT,
    stage TEXT,
    arr TEXT,
    close_date TEXT,
    health TEXT DEFAULT 'Healthy',
    status_summary TEXT,
    last_call_date TEXT,
    last_call_summary TEXT,
    next_call_date TEXT,
    next_call_time TEXT,
    slack_channel_id TEXT,
    slack_sync_requested_at TEXT,
    salesforce_sync_requested_at TEXT,
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

CREATE TABLE IF NOT EXISTS account_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    changed_at TEXT DEFAULT (datetime('now')),
    source TEXT DEFAULT 'manual',
    status_summary TEXT,
    last_call_date TEXT,
    last_call_summary TEXT,
    next_call_date TEXT,
    next_call_time TEXT
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

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    account_name TEXT,
    title TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    link TEXT,
    synced_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    link TEXT,
    environment TEXT,
    reviewed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def _migrate(conn):
    for ddl in [
        "ALTER TABLE accounts ADD COLUMN slack_sync_requested_at TEXT",
        "ALTER TABLE accounts ADD COLUMN se_assigned TEXT",
        "ALTER TABLE accounts ADD COLUMN stage TEXT",
        "ALTER TABLE accounts ADD COLUMN arr TEXT",
        "ALTER TABLE accounts ADD COLUMN salesforce_sync_requested_at TEXT",
        "ALTER TABLE accounts ADD COLUMN close_date TEXT",
    ]:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # already there


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


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


def log_history(account_id, source="manual", **snapshot):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO account_history (account_id, source, status_summary, last_call_date, "
            "last_call_summary, next_call_date, next_call_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                account_id, source, snapshot.get("status_summary"), snapshot.get("last_call_date"),
                snapshot.get("last_call_summary"), snapshot.get("next_call_date"), snapshot.get("next_call_time"),
            ),
        )


def list_history(account_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM account_history WHERE account_id = ? ORDER BY changed_at DESC", (account_id,)
        ).fetchall()


# ---------- Claude-driven Slack sync requests ----------
# The app has no Slack/Anthropic credentials of its own. "Requesting" a sync
# just timestamps this column; a Claude session with a Slack connector reads
# pending requests, does the fetch + summarize itself, and writes the result
# back via apply_slack_sync.py, which clears the request.

def request_slack_sync(account_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE accounts SET slack_sync_requested_at = ? WHERE id = ?",
            (datetime.now().isoformat(sep=" ", timespec="seconds"), account_id),
        )


def clear_slack_sync_request(account_id):
    with get_conn() as conn:
        conn.execute("UPDATE accounts SET slack_sync_requested_at = NULL WHERE id = ?", (account_id,))


def list_pending_slack_syncs():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM accounts WHERE slack_sync_requested_at IS NOT NULL ORDER BY slack_sync_requested_at"
        ).fetchall()


# ---------- Claude-driven Salesforce sync requests (same idea, for Stage/ARR) ----------

def request_salesforce_sync(account_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE accounts SET salesforce_sync_requested_at = ? WHERE id = ?",
            (datetime.now().isoformat(sep=" ", timespec="seconds"), account_id),
        )


def clear_salesforce_sync_request(account_id):
    with get_conn() as conn:
        conn.execute("UPDATE accounts SET salesforce_sync_requested_at = NULL WHERE id = ?", (account_id,))


def list_pending_salesforce_syncs():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM accounts WHERE salesforce_sync_requested_at IS NOT NULL ORDER BY salesforce_sync_requested_at"
        ).fetchall()


def find_account_by_name(name):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM accounts WHERE name = ? COLLATE NOCASE", (name.strip(),)
        ).fetchone()


# ---------- global "import all my Salesforce accounts" request (Dashboard button) ----------

_SF_IMPORT_KEY = "salesforce_import_requested_at"


def request_salesforce_import():
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_SF_IMPORT_KEY, datetime.now().isoformat(sep=" ", timespec="seconds")),
        )


def clear_salesforce_import_request():
    with get_conn() as conn:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (_SF_IMPORT_KEY,))


def get_salesforce_import_request():
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (_SF_IMPORT_KEY,)).fetchone()
        return row["value"] if row else None


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


# ---------- Claude-driven Google Calendar sync (customer meetings, 4-week view) ----------
# Same pattern as the Salesforce import: the app has no Google credentials of
# its own. A Dashboard button flags the request; a Claude session with a
# Calendar connector reads the next 4 weeks of events itself and writes
# results back via apply_calendar_sync.py, which replaces the whole 4-week
# window's rows and clears the request.

_CAL_SYNC_KEY = "calendar_sync_requested_at"


def _week_start():
    today = datetime.now().date()
    return today - timedelta(days=today.weekday())


def _list_events_between(start_date, end_date):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM calendar_events WHERE substr(start_time, 1, 10) BETWEEN ? AND ? ORDER BY start_time",
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()


def request_calendar_sync():
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_CAL_SYNC_KEY, datetime.now().isoformat(sep=" ", timespec="seconds")),
        )


def clear_calendar_sync_request():
    with get_conn() as conn:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (_CAL_SYNC_KEY,))


def get_calendar_sync_request():
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (_CAL_SYNC_KEY,)).fetchone()
        return row["value"] if row else None


def clear_calendar_events_four_weeks():
    monday = _week_start()
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM calendar_events WHERE substr(start_time, 1, 10) BETWEEN ? AND ?",
            (monday.isoformat(), (monday + timedelta(days=27)).isoformat()),
        )


def add_calendar_event(title, start_time, end_time=None, account_name=None, account_id=None, link=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO calendar_events (account_id, account_name, title, start_time, end_time, link) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, account_name, title, start_time, end_time, link),
        )


def list_calendar_events_this_week():
    monday = _week_start()
    return _list_events_between(monday, monday + timedelta(days=6))


def list_calendar_events_four_weeks():
    monday = _week_start()
    return _list_events_between(monday, monday + timedelta(days=27))


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
