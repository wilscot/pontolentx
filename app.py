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
from holidays import import_current_and_next_year
from punch import detect_chrome_profiles, execute_punch, DryRunAborted
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


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


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

        days.append({
            "date": d,
            "weekday": WEEKDAY_PT[i],
            "is_today": d == today,
            "is_past": d < today,
            "day_type": day_type,
            "day_type_label": DAY_TYPE_LABEL.get(day_type, day_type),
            "notes": notes,
            "punches": punches,
        })

    return days


def _build_two_weeks_data(primary_week_start: str) -> dict:
    primary_start = date.fromisoformat(primary_week_start)
    secondary_start = (primary_start + timedelta(days=7)).isoformat()
    return {
        "week_start": primary_week_start,
        "next_week_start": secondary_start,
        "weeks": [
            _build_week_data(primary_week_start),
            _build_week_data(secondary_start),
        ],
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
    weeks_data = _build_two_weeks_data(monday)
    return render_template(
        "index.html",
        current_week_days=weeks_data["weeks"][0],
        next_week_days=weeks_data["weeks"][1],
        week_start=monday,
        next_week_start=weeks_data["next_week_start"],
        scheduler_running=sched.is_running(),
        today=today.isoformat(),
        day_types=DAY_TYPE_LABEL,
    )


@app.route("/setup", methods=["GET", "POST"])
@login_required
def setup():
    profiles = detect_chrome_profiles()
    config = db.get_all_config()
    error = None

    if request.method == "POST":
        data = request.form
        schedule_pattern_changed = False

        db.set_config("email", data.get("email", "").strip())
        db.set_config("local_coletor", data.get("local_coletor", "").strip())
        db.set_config("chrome_profile_name", "Default")
        db.set_config("headless_mode", "1" if data.get("headless_mode") == "1" else "0")

        # Use the dedicated automation profile path (editable by user)
        # Silently replace main Chrome User Data dir — it's always locked
        custom_path = data.get("chrome_profile_path", "").strip()
        if custom_path and not _is_main_chrome_dir(custom_path):
            db.set_config("chrome_profile_path", custom_path)
        elif _is_main_chrome_dir(custom_path):
            db.set_config("chrome_profile_path", _dedicated_profile_path())

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

    # Always show a usable profile path — replace main Chrome dir if it slipped into DB
    dedicated_default = _dedicated_profile_path()
    if not config.get("chrome_profile_path") or _is_main_chrome_dir(config.get("chrome_profile_path", "")):
        config["chrome_profile_path"] = dedicated_default

    return render_template(
        "setup.html",
        profiles=profiles,
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


# --- chrome profile setup ---

# Holds the active Playwright setup context so it can be closed on demand
_setup_context = None
_setup_context_lock = threading.Lock()
_setup_done_event = threading.Event()


def _dedicated_profile_path() -> str:
    base_dir = Path(os.getenv("PTX_RUNTIME_DIR", Path(__file__).parent))
    return str(base_dir / "data" / "chrome-profile")


def _is_main_chrome_dir(path: str) -> bool:
    """Returns True if the path is the main Chrome User Data directory (always locked)."""
    main = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    try:
        return Path(path).resolve() == main.resolve()
    except Exception:
        return False


@app.route("/api/import-session", methods=["POST"])
@login_required
def api_import_session():
    """
    Copies the Cookies file and Local Storage from the personal Chrome Default profile
    into the automation profile so the existing Pontotel session is reused.
    Chrome must be closed during the copy — the Cookies file is locked while Chrome runs.
    """
    import shutil

    src_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data" / "Default"
    automation_profile = db.get_config("chrome_profile_path") or _dedicated_profile_path()
    dst_base = Path(automation_profile) / "Default"

    if not src_base.exists():
        return jsonify({"error": "Perfil padrão do Chrome não encontrado."}), 404

    errors = []

    # Cookies (session tokens)
    src_cookies = src_base / "Network" / "Cookies"
    if src_cookies.exists():
        try:
            dst_net = dst_base / "Network"
            dst_net.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_cookies, dst_net / "Cookies")
        except PermissionError:
            return jsonify({"error": "Feche o Google Chrome completamente antes de importar a sessão."}), 409
        except Exception as exc:
            errors.append(f"Cookies: {exc}")

    # Local Storage (may hold auth tokens)
    src_ls = src_base / "Local Storage"
    if src_ls.exists():
        try:
            dst_ls = dst_base / "Local Storage"
            shutil.copytree(src_ls, dst_ls, dirs_exist_ok=True)
        except PermissionError:
            return jsonify({"error": "Feche o Google Chrome completamente antes de importar a sessão."}), 409
        except Exception as exc:
            errors.append(f"Local Storage: {exc}")

    if errors:
        return jsonify({"error": "Erros parciais: " + "; ".join(errors)}), 500

    return jsonify({"ok": True})


@app.route("/api/open-profile", methods=["POST"])
@login_required
def api_open_profile():
    """
    Launches a dedicated Chrome instance via Playwright with the automation profile.
    Playwright's --remote-debugging-pipe forces a new process regardless of other
    Chrome instances already running, avoiding Chrome's single-instance delegation.
    """
    global _setup_context

    with _setup_context_lock:
        if _setup_context is not None:
            return jsonify({"error": "Chrome de configuração já está aberto"}), 409

    body = request.get_json(silent=True) or {}
    profile_path = body.get("profile_path") or db.get_config("chrome_profile_path")
    if not profile_path or _is_main_chrome_dir(profile_path):
        # Fall back to dedicated path — main Chrome User Data is always locked by running Chrome
        profile_path = _dedicated_profile_path()

    db.set_config("chrome_profile_path", profile_path)
    Path(profile_path).mkdir(parents=True, exist_ok=True)
    _setup_done_event.clear()

    def run_setup_browser():
        global _setup_context
        try:
            from playwright.sync_api import sync_playwright
            print(f"[setup-browser] Iniciando Playwright com perfil: {profile_path}")
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    channel="chrome",
                    headless=False,
                    args=["--profile-directory=Default"],
                    no_viewport=True,
                )
                print("[setup-browser] Chrome aberto com sucesso.")
                page = context.new_page()
                page.goto("https://bateponto.pontotel.com.br/#/")

                with _setup_context_lock:
                    _setup_context = context

                # Keep Chrome open until user signals done or 15 min timeout
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
    return jsonify({"ok": True, "profile_path": profile_path})


@app.route("/api/close-profile", methods=["POST"])
@login_required
def api_close_profile():
    """Signals the setup Chrome instance to close."""
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
        # Visual mode: run in background thread, user interacts with Chrome window
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
