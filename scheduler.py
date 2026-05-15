import random
import threading
from datetime import date, timedelta, datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

import db
from punch import execute_punch

PUNCH_ORDER = ["entrada", "pausa", "retorno", "saida"]
MIN_LUNCH_MINUTES = 60
MAX_LUNCH_MINUTES = 75
MIN_WORK_MINUTES = 7 * 60 + 45
MAX_WORK_MINUTES = 8 * 60 + 15

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


def recalculate_day_schedule(iso_date: str) -> None:
    if iso_date < date.today().isoformat():
        return
    _recalculate_day_entries(iso_date)
    _reschedule_pending_entries_for_date(iso_date)


def recalculate_day_after_registered(entry_id: int) -> None:
    entry = db.get_schedule_entry(entry_id)
    if not entry or entry["status"] != "registrado":
        return
    recalculate_day_schedule(entry["date"])


# --- internal ---

def _daily_setup() -> None:
    """Runs at midnight: ensures today's pending punches are scheduled as APScheduler jobs."""
    today_obj = date.today()
    today = today_obj.isoformat()
    db.mark_past_pending_as_not_executed(today)
    ensure_schedule_horizon(
        today_obj,
        weeks=4,
        recalculate_all=today_obj.day == 1,
    )
    _load_pending_jobs_for_date(today)


def _weekly_generate() -> None:
    today = date.today()
    next_monday = (_get_monday(today) + timedelta(days=7)).isoformat()
    ensure_schedule_horizon(today, weeks=4, recalc_week_start=next_monday)


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
        recalculate_day_after_registered(schedule_id)
    except Exception:
        pass


# --- schedule generation ---

def ensure_schedule_horizon(
    anchor_date: date,
    weeks: int = 4,
    recalc_week_start: str | None = None,
    recalculate_all: bool = False,
) -> None:
    base_monday = _get_monday(anchor_date)
    for week_offset in range(weeks):
        monday = (base_monday + timedelta(days=7 * week_offset)).isoformat()
        if recalculate_all:
            generate_week_schedule(monday, recalculate_existing=True)
            continue
        should_recalc = recalc_week_start == monday
        if should_recalc:
            generate_week_schedule(monday, recalculate_existing=True)
            continue
        if not db.week_has_schedule(monday):
            generate_week_schedule(monday, recalculate_existing=False)


def recalculate_future_schedule(from_date: date | None = None) -> None:
    """
    Recalculates all already scheduled future weeks from from_date using current base/range config.
    Preserves manual overrides and non-pending statuses.
    """
    anchor = from_date or date.today()
    anchor_iso = anchor.isoformat()

    existing_weeks = db.get_future_schedule_mondays(anchor_iso)
    for monday in existing_weeks:
        generate_week_schedule(monday, recalculate_existing=True)

    # Keep rolling planning horizon complete even if some weeks had no rows yet.
    ensure_schedule_horizon(anchor, weeks=4, recalculate_all=False)

    # If scheduler is running, realign today's jobs to new times.
    _reschedule_pending_entries_for_date(anchor_iso)


def generate_week_schedule(week_start: str, recalculate_existing: bool = False) -> None:
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
                _generate_half_day_entries(target_date, special, config, recalculate_existing=recalculate_existing)
                continue

        _generate_full_day_entries(target_date, config, recalculate_existing=recalculate_existing)


def _generate_full_day_entries(target_date: str, config: dict, recalculate_existing: bool = False) -> None:
    existing_by_type = _entries_by_type(target_date)
    active_types = {
        punch_type
        for punch_type in PUNCH_ORDER
        if existing_by_type.get(punch_type, {}).get("status") != "ignorado"
    }

    if active_types == set(PUNCH_ORDER):
        planned_times = _build_full_day_times(target_date, config, existing_by_type)
    elif active_types == {"entrada", "saida"}:
        planned_times = _build_direct_day_times(target_date, config, existing_by_type)
    else:
        planned_times = _build_individual_times(target_date, config, existing_by_type, active_types)

    for punch_type in PUNCH_ORDER:
        db.insert_schedule_entry(
            target_date,
            punch_type,
            planned_times[punch_type],
            recalculate=recalculate_existing,
        )


def _entries_by_type(target_date: str) -> dict[str, dict]:
    return {
        row["punch_type"]: row
        for row in db.get_schedule_for_date(target_date)
    }


def _build_full_day_times(target_date: str, config: dict, existing_by_type: dict[str, dict]) -> dict[str, str]:
    entrada = _entry_time_or_random("entrada", target_date, config, existing_by_type)
    pausa = _entry_time_or_random("pausa", target_date, config, existing_by_type)
    retorno = _entry_time_or_lunch_return("retorno", target_date, pausa, existing_by_type)
    saida = _entry_time_or_workday_exit(
        "saida",
        target_date,
        entrada,
        pausa,
        retorno,
        existing_by_type,
    )
    return {
        "entrada": entrada,
        "pausa": pausa,
        "retorno": retorno,
        "saida": saida,
    }


def _build_direct_day_times(target_date: str, config: dict, existing_by_type: dict[str, dict]) -> dict[str, str]:
    entrada = _entry_time_or_random("entrada", target_date, config, existing_by_type)
    saida = _entry_time_or_direct_exit("saida", target_date, entrada, existing_by_type)
    return {
        "entrada": entrada,
        "pausa": _entry_time_or_random("pausa", target_date, config, existing_by_type),
        "retorno": _entry_time_or_random("retorno", target_date, config, existing_by_type),
        "saida": saida,
    }


def _build_individual_times(
    target_date: str,
    config: dict,
    existing_by_type: dict[str, dict],
    active_types: set[str],
) -> dict[str, str]:
    times = {}
    for punch_type in PUNCH_ORDER:
        if punch_type not in active_types and punch_type in existing_by_type:
            times[punch_type] = existing_by_type[punch_type]["scheduled_time"]
        else:
            times[punch_type] = _entry_time_or_random(punch_type, target_date, config, existing_by_type)
    return times


def _generate_half_day_entries(
    target_date: str,
    special: dict,
    config: dict,
    recalculate_existing: bool = False,
) -> None:
    import json
    custom = {}
    try:
        custom = json.loads(special.get("custom_json") or "{}")
    except (ValueError, TypeError):
        pass

    # Custom schedule takes precedence; fallback to base times without ranges
    for punch_type in custom.get("punch_types", ["entrada", "saida"]):
        scheduled_time = custom.get(punch_type) or config.get(f"{punch_type}_base", "07:30")
        db.insert_schedule_entry(target_date, punch_type, scheduled_time, recalculate=recalculate_existing)


def _entry_time_or_random(
    punch_type: str,
    target_date: str,
    config: dict,
    existing_by_type: dict[str, dict],
) -> str:
    entry = existing_by_type.get(punch_type)
    if entry and _is_auto_recalc_protected(entry):
        return entry["actual_time"] or entry["scheduled_time"]
    return _random_time(
        base=config.get(f"{punch_type}_base", "07:30"),
        range_before=int(config.get(f"{punch_type}_range_antes", "10")),
        range_after=int(config.get(f"{punch_type}_range_depois", "15")),
        previous_minute=db.get_previous_minute_for_type(punch_type, target_date),
    )


def _entry_time_or_lunch_return(
    punch_type: str,
    target_date: str,
    pausa: str,
    existing_by_type: dict[str, dict],
) -> str:
    entry = existing_by_type.get(punch_type)
    if entry and _is_auto_recalc_protected(entry):
        return entry["actual_time"] or entry["scheduled_time"]
    pausa_min = _time_to_minutes(pausa)
    return _minutes_to_time(
        pausa_min + _choose_lunch_minutes(
            pausa_min,
            db.get_previous_minute_for_type(punch_type, target_date),
        )
    )


def _entry_time_or_workday_exit(
    punch_type: str,
    target_date: str,
    entrada: str,
    pausa: str,
    retorno: str,
    existing_by_type: dict[str, dict],
) -> str:
    entry = existing_by_type.get(punch_type)
    if entry and _is_auto_recalc_protected(entry):
        return entry["actual_time"] or entry["scheduled_time"]

    entrada_min = _time_to_minutes(entrada)
    pausa_min = _time_to_minutes(pausa)
    retorno_min = _time_to_minutes(retorno)
    morning_minutes = max(0, pausa_min - entrada_min)
    work_target = _choose_work_minutes_for_exit(
        retorno_min,
        morning_minutes,
        db.get_previous_minute_for_type(punch_type, target_date),
    )
    return _minutes_to_time(retorno_min + max(0, work_target - morning_minutes))


def _entry_time_or_direct_exit(
    punch_type: str,
    target_date: str,
    entrada: str,
    existing_by_type: dict[str, dict],
) -> str:
    entry = existing_by_type.get(punch_type)
    if entry and _is_auto_recalc_protected(entry):
        return entry["actual_time"] or entry["scheduled_time"]
    entrada_min = _time_to_minutes(entrada)
    work_target = _choose_work_minutes_for_exit(
        entrada_min,
        0,
        db.get_previous_minute_for_type(punch_type, target_date),
    )
    return _minutes_to_time(entrada_min + work_target)


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


def _time_to_minutes(time_str: str) -> int:
    hour, minute = map(int, time_str.split(":"))
    return hour * 60 + minute


def _minutes_to_time(total_minutes: int) -> str:
    hour = (total_minutes // 60) % 24
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"


def _choose_lunch_minutes(pausa_minute: int, previous_minute: int | None = None) -> int:
    candidates = list(range(MIN_LUNCH_MINUTES, MAX_LUNCH_MINUTES + 1))
    if previous_minute is not None:
        filtered = [m for m in candidates if ((pausa_minute + m) % 60) != previous_minute]
        if filtered:
            candidates = filtered
    return random.choice(candidates)


def _choose_work_minutes() -> int:
    return random.randint(MIN_WORK_MINUTES, MAX_WORK_MINUTES)


def _choose_work_minutes_for_exit(start_minute: int, worked_before: int, previous_minute: int | None = None) -> int:
    candidates = list(range(MIN_WORK_MINUTES, MAX_WORK_MINUTES + 1))
    random.shuffle(candidates)
    if previous_minute is None:
        return candidates[0]
    for target in candidates:
        exit_minute = start_minute + max(0, target - worked_before)
        if exit_minute % 60 != previous_minute:
            return target
    return candidates[0]


def _is_auto_recalc_protected(entry: dict) -> bool:
    return entry["status"] != "pendente" or entry["manual_override"] == 1


def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _recalculate_day_entries(iso_date: str) -> None:
    rows = db.get_schedule_for_date(iso_date)
    entries = {row["punch_type"]: row for row in rows}
    active_types = {
        punch_type
        for punch_type, entry in entries.items()
        if punch_type in PUNCH_ORDER and entry["status"] != "ignorado"
    }

    if active_types == set(PUNCH_ORDER):
        _recalculate_full_day(iso_date, entries)
    elif active_types == {"entrada", "saida"}:
        _recalculate_direct_day(iso_date, entries)


def _recalculate_full_day(iso_date: str, entries: dict[str, dict]) -> None:
    values = _entry_minutes_by_type(entries)
    entrada = values.get("entrada")
    pausa = values.get("pausa")
    retorno = values.get("retorno")
    saida = values.get("saida")
    if None in (entrada, pausa, retorno, saida):
        return

    lunch_minutes = retorno - pausa
    if not (MIN_LUNCH_MINUTES <= lunch_minutes <= MAX_LUNCH_MINUTES):
        retorno_entry = entries["retorno"]
        new_retorno = pausa + _choose_lunch_minutes(pausa)
        if _can_auto_update_entry(retorno_entry, iso_date, new_retorno):
            retorno = new_retorno
            db.update_schedule_time_auto(retorno_entry["id"], _minutes_to_time(retorno))
            values["retorno"] = retorno

    worked_minutes = _planned_full_day_work(values)
    if worked_minutes is not None and MIN_WORK_MINUTES <= worked_minutes <= MAX_WORK_MINUTES:
        return

    saida_entry = entries["saida"]
    morning_minutes = pausa - entrada
    if morning_minutes < 0 or retorno <= pausa:
        return
    target = _choose_work_minutes_for_exit(retorno, morning_minutes)
    new_saida = retorno + max(0, target - morning_minutes)
    if not _can_auto_update_entry(saida_entry, iso_date, new_saida):
        return
    db.update_schedule_time_auto(
        saida_entry["id"],
        _minutes_to_time(new_saida),
    )


def _recalculate_direct_day(iso_date: str, entries: dict[str, dict]) -> None:
    values = _entry_minutes_by_type(entries)
    entrada = values.get("entrada")
    saida = values.get("saida")
    if entrada is None or saida is None:
        return

    worked_minutes = saida - entrada
    if MIN_WORK_MINUTES <= worked_minutes <= MAX_WORK_MINUTES:
        return

    saida_entry = entries["saida"]
    target = _choose_work_minutes_for_exit(entrada, 0)
    new_saida = entrada + target
    if not _can_auto_update_entry(saida_entry, iso_date, new_saida):
        return
    db.update_schedule_time_auto(saida_entry["id"], _minutes_to_time(new_saida))


def _entry_minutes_by_type(entries: dict[str, dict]) -> dict[str, int | None]:
    values = {}
    for punch_type, entry in entries.items():
        if entry["status"] == "ignorado":
            continue
        time_value = entry["actual_time"] if entry["status"] == "registrado" else entry["scheduled_time"]
        values[punch_type] = _time_to_minutes(time_value) if time_value else None
    return values


def _planned_full_day_work(values: dict[str, int | None]) -> int | None:
    entrada = values.get("entrada")
    pausa = values.get("pausa")
    retorno = values.get("retorno")
    saida = values.get("saida")
    if None in (entrada, pausa, retorno, saida):
        return None
    if pausa <= entrada or saida <= retorno:
        return None
    return (pausa - entrada) + (saida - retorno)


def _can_auto_update_entry(entry: dict, iso_date: str, candidate_minutes: int | None = None) -> bool:
    if _is_auto_recalc_protected(entry):
        return False
    today = date.today().isoformat()
    if iso_date < today:
        return False
    if iso_date > today:
        return True
    if candidate_minutes is None:
        return True
    now = datetime.now()
    return candidate_minutes > now.hour * 60 + now.minute


def _reschedule_pending_entries_for_date(iso_date: str) -> None:
    if not is_running():
        return
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM schedule WHERE date = ? AND status = 'pendente'",
            (iso_date,),
        ).fetchall()
    for row in rows:
        reschedule_entry(row["id"])
