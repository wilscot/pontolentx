import json
import os
import queue
import threading
import webbrowser
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

import db
import scheduler as sched
from browser_profiles import (
    get_browser_label,
    get_dedicated_profile_path,
    get_personal_default_profile_dir,
    get_playwright_channel,
    get_profile_config_key,
    is_main_user_data_dir,
    iter_browser_keys,
    normalize_browser,
)
from holidays import import_current_and_next_year
from punch import execute_punch, DryRunAborted
from scheduler import cancel_entry_job

# Queue used by headless test-run to stream log steps to the SSE endpoint
_test_run_queue: queue.Queue = queue.Queue()
_test_run_lock = threading.Lock()
_test_run_active = False

app = Flask(__name__)

PUNCH_LABEL = {
    "entrada": "Entrada",
    "pausa": "Pausa almoço",
    "retorno": "Retorno",
    "saida": "Saída",
}

DAY_TYPE_LABEL = {
    "normal": "Normal",
    "feriado": "Feriado",
    "folga": "Folga",
    "facultativo": "Ponto facultativo",
    "meio_expediente": "Meio expediente",
}

WEEKDAY_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"]
MONTH_ABBR_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MONTH_FULL_PT = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]
OFF_DAY_TYPES = {"feriado", "folga", "facultativo"}
DAILY_WORK_TARGET_MINUTES = 8 * 60


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _time_to_minutes(time_str: str | None) -> int | None:
    if not time_str:
        return None
    try:
        hour, minute = map(int, time_str.split(":"))
    except (TypeError, ValueError):
        return None
    return hour * 60 + minute


def _format_duration_label(total_minutes: int) -> str:
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{hours:02d}:{minutes:02d}"


def _format_duration_human(total_minutes: int, include_plus: bool = False) -> str:
    sign = ""
    if total_minutes < 0:
        sign = "-"
    elif include_plus and total_minutes > 0:
        sign = "+"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours}h {minutes:02d}m"


def _format_range_label(start: date, end: date) -> str:
    return f"{start.day:02d}/{start.month:02d} — {end.day:02d}/{end.month:02d}"


def _format_nav_range_label(start: date, end: date) -> str:
    return (
        f"{start.day:02d} {MONTH_ABBR_PT[start.month - 1]} — "
        f"{end.day:02d} {MONTH_ABBR_PT[end.month - 1]}"
    )


def _format_nav_subtitle(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        return f"2 semanas · {MONTH_FULL_PT[start.month - 1]} {start.year}"
    if start.year == end.year:
        return (
            f"2 semanas · {MONTH_ABBR_PT[start.month - 1]}/"
            f"{MONTH_ABBR_PT[end.month - 1]} {start.year}"
        )
    return (
        f"2 semanas · {MONTH_ABBR_PT[start.month - 1]}/{start.year} — "
        f"{MONTH_ABBR_PT[end.month - 1]}/{end.year}"
    )


def _build_day_balance(punches: list[dict]) -> dict:
    actual_by_type = {
        punch["punch_type"]: _time_to_minutes(punch.get("actual_time"))
        for punch in punches
    }

    entrada = actual_by_type.get("entrada")
    pausa = actual_by_type.get("pausa")
    retorno = actual_by_type.get("retorno")
    saida = actual_by_type.get("saida")

    worked_minutes = None

    # Only closed days contribute to the balance: a full workday or a direct entrada->saida pair.
    if (
        entrada is not None
        and pausa is not None
        and retorno is not None
        and saida is not None
        and pausa > entrada
        and saida > retorno
    ):
        worked_minutes = (pausa - entrada) + (saida - retorno)
    elif (
        entrada is not None
        and saida is not None
        and pausa is None
        and retorno is None
        and saida > entrada
    ):
        worked_minutes = saida - entrada

    if worked_minutes is None:
        return {
            "worked_minutes": None,
            "balance_minutes": None,
            "balance_label": None,
            "balance_title": None,
            "balance_type": None,
            "show_balance": False,
        }

    balance_minutes = worked_minutes - DAILY_WORK_TARGET_MINUTES
    if balance_minutes > 0:
        balance_title = "Hora extra"
        balance_type = "extra"
    elif balance_minutes < 0:
        balance_title = "Horas devendo"
        balance_type = "negative"
    else:
        balance_title = "Saldo do dia"
        balance_type = "neutral"

    return {
        "worked_minutes": worked_minutes,
        "balance_minutes": balance_minutes,
        "balance_label": _format_duration_label(balance_minutes),
        "balance_title": balance_title,
        "balance_type": balance_type,
        "show_balance": True,
    }


def _build_week_data(week_start: str) -> list[dict]:
    today = date.today().isoformat()
    db.mark_past_pending_as_not_executed(today)

    schedule_rows = {
        (r["date"], r["punch_type"]): r
        for r in db.get_week_schedule(week_start)
    }
    special_days = db.get_special_days_for_week(week_start)

    start = date.fromisoformat(week_start)
    days = []

    for i in range(5):
        d = (start + timedelta(days=i)).isoformat()
        special = special_days.get(d)
        day_type = special["day_type"] if special else "normal"
        notes = special["notes"] if special else ""

        punches = []
        for punch_type in sched.PUNCH_ORDER:
            entry = schedule_rows.get((d, punch_type))
            punches.append({
                "punch_type": punch_type,
                "label": PUNCH_LABEL[punch_type],
                "id": entry["id"] if entry else None,
                "scheduled_time": entry["scheduled_time"] if entry else None,
                "actual_time": entry["actual_time"] if entry else None,
                "status": entry["status"] if entry else None,
            })

        balance = _build_day_balance(punches)
        days.append({
            "date": d,
            "weekday": WEEKDAY_PT[i],
            "is_today": d == today,
            "is_past": d < today,
            "day_type": day_type,
            "day_type_label": DAY_TYPE_LABEL.get(day_type, day_type),
            "notes": notes,
            "punches": punches,
            **balance,
        })

    return days


def _find_next_punch(days: list[dict]) -> dict:
    today_iso = date.today().isoformat()
    for day in days:
        if day["date"] < today_iso:
            continue
        for punch in day["punches"]:
            if not punch.get("scheduled_time"):
                continue
            if punch.get("status") in {"registrado", "ignorado", "erro", "nao_executado"}:
                continue
            when_label = "hoje" if day["is_today"] else f"{day['weekday']} · {day['date'][8:]}/{day['date'][5:7]}"
            return {
                "value": punch["scheduled_time"],
                "hint": f"{punch['label']} · {when_label}",
            }

    return {
        "value": "--",
        "hint": "sem próximos pontos na janela exibida",
    }


def _build_dashboard_summary(weeks: list[list[dict]]) -> dict:
    all_days = [day for week in weeks for day in week]
    scheduled_punches = [
        punch
        for day in all_days
        for punch in day["punches"]
        if punch.get("scheduled_time")
    ]
    executed_count = sum(punch.get("status") == "registrado" for punch in scheduled_punches)

    closed_days = [day for day in all_days if day.get("worked_minutes") is not None]
    worked_minutes = sum(day["worked_minutes"] for day in closed_days) if closed_days else 0
    expected_minutes = DAILY_WORK_TARGET_MINUTES * len(closed_days)
    balance_minutes = sum(day["balance_minutes"] for day in closed_days) if closed_days else 0
    next_punch = _find_next_punch(all_days)

    if balance_minutes > 0:
        balance_accent = "overtime"
        balance_hint = "saldo positivo"
    elif balance_minutes < 0:
        balance_accent = "danger"
        balance_hint = "horas devendo"
    else:
        balance_accent = "muted"
        balance_hint = "saldo zerado"

    worked_hint = (
        f"de {_format_duration_human(expected_minutes)} previstas"
        if closed_days
        else "sem dias concluídos"
    )

    return {
        "metrics": [
            {
                "label": "Pontos batidos",
                "value": f"{executed_count}/{len(scheduled_punches)}",
                "hint": "na janela exibida",
                "accent": "success",
            },
            {
                "label": "Horas trabalhadas",
                "value": _format_duration_human(worked_minutes),
                "hint": worked_hint,
                "accent": "muted",
            },
            {
                "label": "Banco de horas",
                "value": _format_duration_human(balance_minutes, include_plus=True),
                "hint": balance_hint,
                "accent": balance_accent,
            },
            {
                "label": "Próximo ponto",
                "value": next_punch["value"],
                "hint": next_punch["hint"],
                "accent": "primary",
            },
        ]
    }


def _build_dashboard_labels(primary_start: date, secondary_start: date) -> dict:
    primary_end = primary_start + timedelta(days=4)
    secondary_end = secondary_start + timedelta(days=4)
    return {
        "nav_range": _format_nav_range_label(primary_start, secondary_end),
        "nav_subtitle": _format_nav_subtitle(primary_start, secondary_end),
        "weeks": [
            {
                "title": "Semana atual",
                "range": _format_range_label(primary_start, primary_end),
            },
            {
                "title": "Próxima semana",
                "range": _format_range_label(secondary_start, secondary_end),
            },
        ],
    }


def _build_two_weeks_data(primary_week_start: str) -> dict:
    primary_start = date.fromisoformat(primary_week_start)
    secondary_start = (primary_start + timedelta(days=7)).isoformat()
    weeks = [
        _build_week_data(primary_week_start),
        _build_week_data(secondary_start),
    ]
    return {
        "week_start": primary_week_start,
        "next_week_start": secondary_start,
        "weeks": weeks,
        "labels": _build_dashboard_labels(primary_start, date.fromisoformat(secondary_start)),
        "summary": _build_dashboard_summary(weeks),
    }


# --- auth ---

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if db.check_credentials(username, password):
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Usuário ou senha inválidos."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# --- pages ---

@app.route("/")
@login_required
def index():
    if not db.is_configured():
        return redirect(url_for("setup"))

    today = date.today()
    monday = _get_monday(today).isoformat()
    sched.ensure_schedule_horizon(today, weeks=4)
    dashboard_data = _build_two_weeks_data(monday)
    return render_template(
        "index.html",
        dashboard=dashboard_data,
        scheduler_running=sched.is_running(),
        today=today.isoformat(),
    )


@app.route("/setup", methods=["GET", "POST"])
@login_required
def setup():
    config = db.get_all_config()
    error = None

    if request.method == "POST":
        data = request.form
        schedule_pattern_changed = False

        browser_channel = normalize_browser(data.get("browser_channel"))
        db.set_config("email", data.get("email", "").strip())
        db.set_config("local_coletor", data.get("local_coletor", "").strip())
        db.set_config("browser_channel", browser_channel)
        db.set_config("chrome_profile_name", "Default")
        db.set_config("headless_mode", "1" if data.get("headless_mode") == "1" else "0")

        for browser in iter_browser_keys():
            config_key = get_profile_config_key(browser)
            db.set_config(config_key, _sanitize_profile_path(browser, data.get(config_key)))

        raw_senha = data.get("senha", "").strip()
        if raw_senha:
            db.set_config("senha_enc", db.encrypt(raw_senha))

        raw_pin = data.get("pin", "").strip()
        if raw_pin:
            db.set_config("pin_enc", db.encrypt(raw_pin))

        for punch_type in ["entrada", "pausa", "retorno", "saida"]:
            base_key = f"{punch_type}_base"
            before_key = f"{punch_type}_range_antes"
            after_key = f"{punch_type}_range_depois"

            new_base = data.get(base_key, "").strip()
            new_before = data.get(before_key, "10").strip()
            new_after = data.get(after_key, "15").strip()

            if (
                new_base != config.get(base_key, "")
                or new_before != config.get(before_key, "10")
                or new_after != config.get(after_key, "15")
            ):
                schedule_pattern_changed = True

            db.set_config(base_key, new_base)
            db.set_config(before_key, new_before)
            db.set_config(after_key, new_after)

        if schedule_pattern_changed:
            sched.recalculate_future_schedule(date.today())

        return redirect(url_for("index"))

    config["browser_channel"] = normalize_browser(config.get("browser_channel"))
    for browser in iter_browser_keys():
        config_key = get_profile_config_key(browser)
        config[config_key] = _sanitize_profile_path(browser, config.get(config_key, ""))

    return render_template(
        "setup.html",
        config=config,
        error=error,
        punch_labels=PUNCH_LABEL,
    )


# --- scheduler API ---

@app.route("/api/scheduler/start", methods=["POST"])
@login_required
def api_scheduler_start():
    sched.start()
    return jsonify({"running": True})


@app.route("/api/scheduler/stop", methods=["POST"])
@login_required
def api_scheduler_stop():
    sched.stop()
    return jsonify({"running": False})


@app.route("/api/scheduler/status")
@login_required
def api_scheduler_status():
    return jsonify({"running": sched.is_running()})


# --- schedule API ---

@app.route("/api/schedule/<int:entry_id>", methods=["PATCH"])
@login_required
def api_update_schedule(entry_id: int):
    data = request.get_json()
    new_time = data.get("scheduled_time", "").strip()

    if not new_time or len(new_time) != 5 or ":" not in new_time:
        return jsonify({"error": "Horário inválido"}), 400

    entry = db.get_schedule_entry(entry_id)
    if not entry:
        return jsonify({"error": "Entrada não encontrada"}), 404

    db.update_schedule_time(entry_id, new_time)
    sched.reschedule_entry(entry_id)

    return jsonify({"ok": True, "scheduled_time": new_time})


# --- special days API ---

@app.route("/api/special-day", methods=["POST"])
@login_required
def api_set_special_day():
    data = request.get_json()
    iso_date = data.get("date")
    day_type = data.get("day_type")
    notes = data.get("notes", "")
    custom_json = data.get("custom_json", "{}")

    if not iso_date or not day_type:
        return jsonify({"error": "Parâmetros ausentes"}), 400

    db.set_special_day(iso_date, day_type, notes, custom_json)

    if day_type in ("feriado", "folga", "facultativo"):
        db.delete_schedule_for_date(iso_date)

    if day_type == "meio_expediente":
        db.delete_schedule_for_date(iso_date)
        config = db.get_all_config()
        sched._generate_half_day_entries(iso_date, {"custom_json": custom_json}, config)

    return jsonify({"ok": True})


@app.route("/api/special-day/<iso_date>", methods=["DELETE"])
@login_required
def api_delete_special_day(iso_date: str):
    db.delete_special_day(iso_date)
    # Regenerate normal schedule for this day if it's in the future
    if iso_date >= date.today().isoformat():
        db.delete_schedule_for_date(iso_date)
        config = db.get_all_config()
        sched._generate_full_day_entries(iso_date, config)
        if sched.is_running():
            _load_jobs_for_date(iso_date)
    return jsonify({"ok": True})


def _load_jobs_for_date(iso_date: str) -> None:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule WHERE date = ? AND status = 'pendente'",
            (iso_date,),
        ).fetchall()
    for row in rows:
        sched._schedule_punch_job(dict(row))


# --- holidays API ---

@app.route("/api/holidays/import", methods=["POST"])
@login_required
def api_import_holidays():
    try:
        imported, skipped = import_current_and_next_year()
        return jsonify({"imported": imported, "skipped": skipped})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# --- week navigation API ---

@app.route("/api/week/<week_start>")
@login_required
def api_week(week_start: str):
    try:
        week_start_date = date.fromisoformat(week_start)
    except ValueError:
        return jsonify({"error": "Data inválida"}), 400

    current_monday = _get_monday(date.today())
    if week_start_date >= current_monday:
        sched.ensure_schedule_horizon(week_start_date, weeks=4)

    return jsonify(_build_two_weeks_data(week_start))


# --- browser profile setup ---

# Holds the active Playwright setup context so it can be closed on demand
_setup_context = None
_setup_context_lock = threading.Lock()
_setup_done_event = threading.Event()


def _sanitize_profile_path(browser: str, path: str | None) -> str:
    sanitized = (path or "").strip()
    if not sanitized or is_main_user_data_dir(sanitized, browser):
        return get_dedicated_profile_path(browser)
    return sanitized


def _locked_browser_message(source_label: str, target_label: str) -> str:
    if source_label == target_label:
        return f"Feche o {source_label} completamente antes de importar a sessão."
    return f"Feche o {source_label} e o {target_label} completamente antes de importar a sessão."


@app.route("/api/import-session", methods=["POST"])
@login_required
def api_import_session():
    """
    Copies Cookies and Local Storage from the personal browser profile into the
    selected automation profile so the existing Pontotel session can be reused.
    """
    import shutil

    body = request.get_json(silent=True) or {}
    source_browser = normalize_browser(body.get("source_browser") or body.get("browser"))
    target_browser = normalize_browser(body.get("target_browser") or db.get_config("browser_channel"))
    source_label = get_browser_label(source_browser)
    target_label = get_browser_label(target_browser)
    target_profile_key = get_profile_config_key(target_browser)

    src_base = get_personal_default_profile_dir(source_browser)
    automation_profile = _sanitize_profile_path(
        target_browser,
        body.get("profile_path") or db.get_config(target_profile_key),
    )
    dst_base = Path(automation_profile) / "Default"

    if not src_base.exists():
        return jsonify({"error": f"Perfil padrão do {source_label} não encontrado."}), 404

    db.set_config(target_profile_key, automation_profile)

    errors = []

    # Cookies (session tokens)
    src_cookies = src_base / "Network" / "Cookies"
    if src_cookies.exists():
        try:
            dst_net = dst_base / "Network"
            dst_net.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_cookies, dst_net / "Cookies")
        except PermissionError:
            return jsonify({"error": _locked_browser_message(source_label, target_label)}), 409
        except Exception as exc:
            errors.append(f"Cookies: {exc}")

    # Local Storage (may hold auth tokens)
    src_ls = src_base / "Local Storage"
    if src_ls.exists():
        try:
            dst_ls = dst_base / "Local Storage"
            shutil.copytree(src_ls, dst_ls, dirs_exist_ok=True)
        except PermissionError:
            return jsonify({"error": _locked_browser_message(source_label, target_label)}), 409
        except Exception as exc:
            errors.append(f"Local Storage: {exc}")

    if errors:
        return jsonify({"error": "Erros parciais: " + "; ".join(errors)}), 500

    return jsonify(
        {
            "ok": True,
            "profile_path": automation_profile,
            "source_browser": source_browser,
            "source_label": source_label,
            "target_browser": target_browser,
            "target_label": target_label,
        }
    )


@app.route("/api/open-profile", methods=["POST"])
@login_required
def api_open_profile():
    """
    Launches a dedicated browser instance via Playwright with the automation
    profile. Playwright's remote debugging pipe forces a new process regardless
    of other browser instances already running.
    """
    global _setup_context

    with _setup_context_lock:
        if _setup_context is not None:
            return jsonify({"error": "Já existe um navegador de configuração aberto."}), 409

    body = request.get_json(silent=True) or {}
    browser = normalize_browser(body.get("browser") or db.get_config("browser_channel"))
    browser_label = get_browser_label(browser)
    config_key = get_profile_config_key(browser)
    profile_path = _sanitize_profile_path(browser, body.get("profile_path") or db.get_config(config_key))

    db.set_config(config_key, profile_path)
    Path(profile_path).mkdir(parents=True, exist_ok=True)
    _setup_done_event.clear()

    def run_setup_browser():
        global _setup_context
        try:
            from playwright.sync_api import sync_playwright
            print(f"[setup-browser] Iniciando {browser_label} com perfil: {profile_path}")
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    channel=get_playwright_channel(browser),
                    headless=False,
                    args=["--profile-directory=Default"],
                    no_viewport=True,
                )
                print(f"[setup-browser] {browser_label} aberto com sucesso.")
                page = context.new_page()
                page.goto("https://bateponto.pontotel.com.br/#/")

                with _setup_context_lock:
                    _setup_context = context

                # Keep the setup browser open until user signals done or 15 min timeout
                _setup_done_event.wait(timeout=900)

                try:
                    context.close()
                except Exception:
                    pass

                with _setup_context_lock:
                    _setup_context = None
        except Exception as exc:
            print(f"[setup-browser] ERRO: {exc}")
            with _setup_context_lock:
                _setup_context = None

    threading.Thread(target=run_setup_browser, daemon=True).start()
    return jsonify(
        {
            "ok": True,
            "browser": browser,
            "browser_label": browser_label,
            "profile_path": profile_path,
        }
    )


@app.route("/api/close-profile", methods=["POST"])
@login_required
def api_close_profile():
    """Signals the active setup browser instance to close."""
    _setup_done_event.set()
    return jsonify({"ok": True})


# --- test-run API ---

@app.route("/api/test-run", methods=["POST"])
@login_required
def api_test_run():
    global _test_run_active

    with _test_run_lock:
        if _test_run_active:
            return jsonify({"error": "Teste já em andamento"}), 409
        _test_run_active = True

    data = request.get_json()
    punch_type = data.get("punch_type", "entrada")
    mode = data.get("mode", "visual")

    if mode == "headless":
        # Clear previous log entries
        while not _test_run_queue.empty():
            try:
                _test_run_queue.get_nowait()
            except queue.Empty:
                break

        def run_headless_test():
            global _test_run_active
            def callback(message: str, ok: bool):
                _test_run_queue.put({"step": message, "ok": ok})
            try:
                execute_punch(punch_type, -1, dry_run=True, log_callback=callback)
            except Exception as exc:
                _test_run_queue.put({"step": str(exc), "ok": False})
            finally:
                _test_run_queue.put(None)  # sentinel — stream ended
                with _test_run_lock:
                    _test_run_active = False

        threading.Thread(target=run_headless_test, daemon=True).start()
        return jsonify({"started": True, "mode": "headless"})

    else:
        # Visual mode: run in background thread, user interacts with the browser window
        def run_visual_test():
            global _test_run_active
            try:
                execute_punch(punch_type, -1, dry_run=True)
            except Exception as exc:
                print(f"[test-run visual] ERRO: {exc}")
            finally:
                with _test_run_lock:
                    _test_run_active = False

        threading.Thread(target=run_visual_test, daemon=True).start()
        return jsonify({"started": True, "mode": "visual"})


@app.route("/api/test-run/stream")
@login_required
def api_test_run_stream():
    """SSE endpoint — streams headless test-run log steps to the browser."""
    def generate():
        while True:
            try:
                item = _test_run_queue.get(timeout=60)
            except queue.Empty:
                yield "data: {\"step\": \"Timeout — nenhuma resposta do teste.\", \"ok\": false}\n\n"
                yield "data: {\"done\": true}\n\n"
                return

            if item is None:
                yield "data: {\"done\": true}\n\n"
                return

            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/punch-now", methods=["POST"])
@login_required
def api_punch_now():
    """Executes a real punch immediately for a given punch_type using today's schedule entry."""
    data = request.get_json()
    punch_type = data.get("punch_type")
    if not punch_type:
        return jsonify({"error": "punch_type ausente"}), 400

    today = date.today().isoformat()
    entry = None
    for row in db.get_week_schedule(today):
        if row["date"] == today and row["punch_type"] == punch_type:
            entry = row
            break

    if not entry:
        return jsonify({"error": "Entrada não encontrada na agenda de hoje"}), 404

    if entry["status"] == "registrado":
        return jsonify({"error": "Este ponto já foi registrado hoje"}), 409

    # Cancel the scheduled APScheduler job so it won't fire again automatically
    cancel_entry_job(entry["id"])

    def run_punch_now():
        try:
            execute_punch(punch_type, entry["id"])
        except Exception as exc:
            print(f"[punch-now] ERRO: {exc}")

    threading.Thread(target=run_punch_now, daemon=True).start()
    return jsonify({"started": True})


def _open_browser() -> None:
    import time
    time.sleep(1)
    webbrowser.open("http://localhost:5000")


def run_server(open_browser: bool = True) -> None:
    db.init_db()
    app.secret_key = db.get_secret_key()

    if db.get_config("scheduler_active") == "1":
        sched.start()

    browser_enabled = open_browser and os.getenv("PTX_DISABLE_AUTO_BROWSER") != "1"
    if browser_enabled:
        threading.Thread(target=_open_browser, daemon=True).start()

    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    run_server(open_browser=True)
