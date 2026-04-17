import sqlite3
import os
from pathlib import Path
from cryptography.fernet import Fernet

BASE_DIR = Path(os.getenv("PTX_RUNTIME_DIR", Path(__file__).parent))
DB_PATH = BASE_DIR / "data" / "ponto.db"
KEY_PATH = BASE_DIR / "data" / ".secret.key"

PUNCH_TYPES = ["entrada", "pausa", "retorno", "saida"]

DEFAULT_CONFIG = {
    "email": "",
    "senha_enc": "",
    "local_coletor": "SETDIG",
    "pin_enc": "",
    "browser_channel": "chrome",
    "chrome_profile_path": "",
    "edge_profile_path": "",
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


def get_secret_key() -> bytes:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _get_fernet_key()


def _fernet() -> Fernet:
    return Fernet(get_secret_key())


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
    get_secret_key()
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
                manual_override INTEGER NOT NULL DEFAULT 0,
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
        _ensure_schedule_migrations(conn)
        conn.commit()
    setup_auth()


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


def _ensure_schedule_migrations(conn: sqlite3.Connection) -> None:
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(schedule)").fetchall()
    }
    if "manual_override" not in cols:
        conn.execute(
            "ALTER TABLE schedule ADD COLUMN manual_override INTEGER NOT NULL DEFAULT 0"
        )


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


def insert_schedule_entry(date: str, punch_type: str, scheduled_time: str, recalculate: bool = False) -> int:
    """
    Inserts schedule entry when absent.
    If recalculate=True, updates existing pending non-manual entries.
    """
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id, status, manual_override FROM schedule WHERE date = ? AND punch_type = ?",
            (date, punch_type),
        ).fetchone()

        if existing:
            entry_id = existing["id"]
            if existing["status"] != "pendente":
                return entry_id
            if existing["manual_override"] == 1:
                return entry_id
            if recalculate:
                conn.execute(
                    """UPDATE schedule
                       SET scheduled_time = ?, status = 'pendente', actual_time = NULL, manual_override = 0
                       WHERE id = ?""",
                    (scheduled_time, entry_id),
                )
                conn.commit()
            return entry_id

        cursor = conn.execute(
            "INSERT INTO schedule (date, punch_type, scheduled_time, status, manual_override) VALUES (?, ?, ?, 'pendente', 0)",
            (date, punch_type, scheduled_time),
        )
        conn.commit()
        return cursor.lastrowid


def update_schedule_time(entry_id: int, scheduled_time: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE schedule SET scheduled_time = ?, status = 'pendente', actual_time = NULL, manual_override = 1 WHERE id = ?",
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


def mark_past_pending_as_not_executed(reference_date: str) -> int:
    """
    Marks past pending entries as not executed.
    reference_date must be ISO (YYYY-MM-DD) and is treated as "today".
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE schedule
               SET status = 'nao_executado'
               WHERE status = 'pendente' AND date < ?""",
            (reference_date,),
        )
        conn.commit()
        return cursor.rowcount


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


def get_future_schedule_mondays(from_date: str) -> list[str]:
    """Returns distinct Monday dates (ISO) for weeks that have schedule rows on/after from_date."""
    from datetime import date, timedelta
    mondays = set()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM schedule WHERE date >= ? ORDER BY date",
            (from_date,),
        ).fetchall()
    for row in rows:
        d = date.fromisoformat(row["date"])
        monday = (d - timedelta(days=d.weekday())).isoformat()
        mondays.add(monday)
    return sorted(mondays)


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


# --- auth ---

def setup_auth() -> None:
    """Seeds login credentials on first run (idempotent)."""
    from werkzeug.security import generate_password_hash
    if not get_config("auth_username"):
        set_config("auth_username", "wfrancischini")
        set_config("auth_password_hash", generate_password_hash("admin123"))


def check_credentials(username: str, password: str) -> bool:
    """Validates username + password against the stored hash."""
    from werkzeug.security import check_password_hash
    stored_user = get_config("auth_username")
    stored_hash = get_config("auth_password_hash")
    if not stored_user or not stored_hash:
        return False
    return username == stored_user and check_password_hash(stored_hash, password)


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
