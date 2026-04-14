import random
import threading
from datetime import date, timedelta, datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

import db
from punch import execute_punch

PUNCH_ORDER = ["entrada", "pausa", "retorno", "saida"]

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


# --- public API ---

def start() -> None:
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            return
        _scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
        _scheduler.add_job(
            _daily_setup,
            CronTrigger(hour=0, minute=1),
            id="daily_setup",
            replace_existing=True,
        )
        _scheduler.add_job(
            _weekly_generate,
            CronTrigger(day_of_week="mon", hour=0, minute=2),
            id="weekly_generate",
            replace_existing=True,
        )
        _scheduler.start()
        db.set_config("scheduler_active", "1")
    # _daily_setup must be called outside _lock — it calls _schedule_punch_job which also acquires _lock
    _daily_setup()


def stop() -> None:
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            _scheduler = None
        db.set_config("scheduler_active", "0")


def is_running() -> bool:
    with _lock:
        return _scheduler is not None and _scheduler.running


def reschedule_entry(entry_id: int) -> None:
    """Called when the user edits a scheduled time — removes old job and adds a new one."""
    if not is_running():
        return
    entry = db.get_schedule_entry(entry_id)
    if not entry or entry["status"] != "pendente":
        return
    job_id = f"punch_{entry_id}"
    with _lock:
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
    _schedule_punch_job(entry)


def cancel_entry_job(entry_id: int) -> None:
    """Removes a scheduled job so it won't fire automatically after a manual punch."""
    if not is_running():
        return
    job_id = f"punch_{entry_id}"
    with _lock:
        if _scheduler and _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)


# --- internal ---

def _daily_setup() -> None:
    """Runs at midnight: ensures today's pending punches are scheduled as APScheduler jobs."""
    today = date.today().isoformat()
    _ensure_week_generated(today)
    _load_pending_jobs_for_date(today)


def _weekly_generate() -> None:
    monday = _get_monday(date.today()).isoformat()
    if not db.week_has_schedule(monday):
        generate_week_schedule(monday)


def _ensure_week_generated(iso_date: str) -> None:
    monday = _get_monday(date.fromisoformat(iso_date)).isoformat()
    if not db.week_has_schedule(monday):
        generate_week_schedule(monday)


def _load_pending_jobs_for_date(iso_date: str) -> None:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule WHERE date = ? AND status = 'pendente'",
            (iso_date,),
        ).fetchall()
    for row in rows:
        _schedule_punch_job(dict(row))


def _schedule_punch_job(entry: dict) -> None:
    scheduled_dt = datetime.fromisoformat(f"{entry['date']} {entry['scheduled_time']}")
    if scheduled_dt <= datetime.now():
        return

    job_id = f"punch_{entry['id']}"
    with _lock:
        if not _scheduler:
            return
        _scheduler.add_job(
            _run_punch,
            DateTrigger(run_date=scheduled_dt),
            args=[entry["punch_type"], entry["id"]],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=300,
        )


def _run_punch(punch_type: str, schedule_id: int) -> None:
    try:
        execute_punch(punch_type, schedule_id)
    except Exception:
        pass


# --- schedule generation ---

def generate_week_schedule(week_start: str) -> None:
    """
    Generates and stores scheduled punch times for Mon-Fri of the given week.
    Applies randomization per punch type and avoids repeating the same minute
    as the previous registered entry for that punch type.
    """
    start = date.fromisoformat(week_start)
    config = db.get_all_config()

    for day_offset in range(5):
        target_date = (start + timedelta(days=day_offset)).isoformat()
        special = db.get_special_day(target_date)

        if special:
            day_type = special["day_type"]
            if day_type in ("feriado", "folga", "facultativo"):
                continue
            if day_type == "meio_expediente":
                _generate_half_day_entries(target_date, special, config)
                continue

        _generate_full_day_entries(target_date, config)


def _generate_full_day_entries(target_date: str, config: dict) -> None:
    for punch_type in PUNCH_ORDER:
        scheduled_time = _random_time(
            base=config.get(f"{punch_type}_base", "07:30"),
            range_before=int(config.get(f"{punch_type}_range_antes", "10")),
            range_after=int(config.get(f"{punch_type}_range_depois", "15")),
            previous_minute=db.get_previous_minute_for_type(punch_type, target_date),
        )
        db.insert_schedule_entry(target_date, punch_type, scheduled_time)


def _generate_half_day_entries(target_date: str, special: dict, config: dict) -> None:
    import json
    custom = {}
    try:
        custom = json.loads(special.get("custom_json") or "{}")
    except (ValueError, TypeError):
        pass

    # Custom schedule takes precedence; fallback to base times without ranges
    for punch_type in custom.get("punch_types", ["entrada", "saida"]):
        scheduled_time = custom.get(punch_type) or config.get(f"{punch_type}_base", "07:30")
        db.insert_schedule_entry(target_date, punch_type, scheduled_time)


def _random_time(base: str, range_before: int, range_after: int, previous_minute: int | None) -> str:
    base_hour, base_min = map(int, base.split(":"))
    base_total = base_hour * 60 + base_min

    candidates = list(range(base_total - range_before, base_total + range_after + 1))
    if previous_minute is not None:
        filtered = [m for m in candidates if (m % 60) != previous_minute]
        if filtered:
            candidates = filtered

    chosen = random.choice(candidates)
    hour = (chosen // 60) % 24
    minute = chosen % 60
    return f"{hour:02d}:{minute:02d}"


def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())
