import sqlite3
import os
from pathlib import Path
from cryptography.fernet import Fernet

DB_PATH = Path(__file__).parent / "data" / "ponto.db"
KEY_PATH = Path(__file__).parent / "data" / ".secret.key"

PUNCH_TYPES = ["entrada", "pausa", "retorno", "saida"]

DEFAULT_CONFIG = {
    "email": "",
    "senha_enc": "",
    "local_coletor": "SETDIG",
    "pin_enc": "",
    "chrome_profile_path": "",
    "chrome_profile_name": "Default",
    "entrada_base": "07:30",
    "pausa_base": "11:30",
    "retorno_base": "12:30",
    "saida_base": "16:30",
    "entrada_range_antes": "10",
    "entrada_range_depois": "15",
    "pausa_range_antes": "10",
    "pausa_range_depois": "15",
    "retorno_range_antes": "10",
    "retorno_range_depois": "15",
    "saida_range_antes": "10",
    "saida_range_depois": "15",
    "scheduler_active": "0",
    "headless_mode": "0",
}


def _get_fernet_key() -> bytes:
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    return key


def _fernet() -> Fernet:
    return Fernet(_get_fernet_key())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except Exception:
        return ""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS schedule (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                date           TEXT NOT NULL,
                punch_type     TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                actual_time    TEXT,
                status         TEXT NOT NULL DEFAULT 'pendente',
                UNIQUE(date, punch_type)
            );

            CREATE TABLE IF NOT EXISTS special_days (
                date        TEXT PRIMARY KEY,
                day_type    TEXT NOT NULL,
                notes       TEXT DEFAULT '',
                custom_json TEXT DEFAULT '{}'
            );
        """)
        for key, value in DEFAULT_CONFIG.items():
            conn.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                (key, value),
            )
        conn.commit()


# --- config ---

def get_config(key: str) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_CONFIG.get(key, "")


def set_config(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()


def get_all_config() -> dict:
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM config").fetchall()
    return {row["key"]: row["value"] for row in rows}


def is_configured() -> bool:
    return bool(get_config("email") and get_config("senha_enc"))


# --- schedule ---

def get_week_schedule(week_start: str) -> list[dict]:
    """week_start: ISO date string of Monday (YYYY-MM-DD)"""
    from datetime import date, timedelta
    start = date.fromisoformat(week_start)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(5)]

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule WHERE date IN ({}) ORDER BY date, punch_type".format(
                ",".join("?" * len(dates))
            ),
            dates,
        ).fetchall()
    return [dict(r) for r in rows]


def get_schedule_entry(entry_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM schedule WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row else None


def insert_schedule_entry(date: str, punch_type: str, scheduled_time: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT OR REPLACE INTO schedule (date, punch_type, scheduled_time, status) VALUES (?, ?, ?, 'pendente')",
            (date, punch_type, scheduled_time),
        )
        conn.commit()
        return cursor.lastrowid


def update_schedule_time(entry_id: int, scheduled_time: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE schedule SET scheduled_time = ?, status = 'pendente', actual_time = NULL WHERE id = ?",
            (scheduled_time, entry_id),
        )
        conn.commit()


def mark_schedule_done(entry_id: int, actual_time: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE schedule SET actual_time = ?, status = 'registrado' WHERE id = ?",
            (actual_time, entry_id),
        )
        conn.commit()


def mark_schedule_error(entry_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE schedule SET status = 'erro' WHERE id = ?",
            (entry_id,),
        )
        conn.commit()


def mark_schedule_ignored(entry_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE schedule SET status = 'ignorado' WHERE id = ?",
            (entry_id,),
        )
        conn.commit()


def get_previous_minute_for_type(punch_type: str, before_date: str) -> int | None:
    """Returns the scheduled minute of the last registered entry for the punch type before the given date."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT scheduled_time FROM schedule
               WHERE punch_type = ? AND date < ?
               ORDER BY date DESC LIMIT 1""",
            (punch_type, before_date),
        ).fetchone()
    if not row:
        return None
    _, minute = row["scheduled_time"].split(":")
    return int(minute)


def week_has_schedule(week_start: str) -> bool:
    from datetime import date, timedelta
    start = date.fromisoformat(week_start)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(5)]
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as n FROM schedule WHERE date IN ({})".format(
                ",".join("?" * len(dates))
            ),
            dates,
        ).fetchone()["n"]
    return count > 0


def delete_schedule_for_date(date: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM schedule WHERE date = ? AND status = 'pendente'", (date,))
        conn.commit()


# --- special_days ---

def get_special_day(date: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM special_days WHERE date = ?", (date,)).fetchone()
    return dict(row) if row else None


def set_special_day(date: str, day_type: str, notes: str = "", custom_json: str = "{}") -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO special_days (date, day_type, notes, custom_json) VALUES (?, ?, ?, ?)",
            (date, day_type, notes, custom_json),
        )
        conn.commit()


def delete_special_day(date: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM special_days WHERE date = ?", (date,))
        conn.commit()


def get_special_days_for_week(week_start: str) -> dict:
    from datetime import date, timedelta
    start = date.fromisoformat(week_start)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(5)]
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM special_days WHERE date IN ({})".format(
                ",".join("?" * len(dates))
            ),
            dates,
        ).fetchall()
    return {row["date"]: dict(row) for row in rows}
