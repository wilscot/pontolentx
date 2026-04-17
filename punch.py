import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import db
from browser_profiles import (
    get_browser_label,
    get_dedicated_profile_path,
    get_playwright_channel,
    get_profile_config_key,
    is_main_user_data_dir,
    normalize_browser,
)


PONTOTEL_URL = "https://bateponto.pontotel.com.br/#/"

PUNCH_BUTTON_PATTERNS = {
    "entrada": re.compile(r"Entrada", re.IGNORECASE),
    "pausa": re.compile(r"Pausa", re.IGNORECASE),
    "retorno": re.compile(r"Retorno", re.IGNORECASE),
    "saida": re.compile(r"Sa[íi]da", re.IGNORECASE),
}

PUNCH_LABEL = {
    "entrada": "Entrada",
    "pausa": "Pausa almoço",
    "retorno": "Retorno",
    "saida": "Saída",
}

# Injected overlay HTML/JS for visual step-by-step dry-run confirmation
_OVERLAY_JS = """
(description) => {
    const existing = document.getElementById('__dryRunOverlay');
    if (existing) existing.remove();
    window.__dryRunResult = null;

    const overlay = document.createElement('div');
    overlay.id = '__dryRunOverlay';
    overlay.style.cssText = [
        'position:fixed','top:0','left:0','width:100%','height:100%',
        'background:rgba(0,0,0,0.72)','z-index:999999',
        'display:flex','align-items:center','justify-content:center',
        'font-family:system-ui,sans-serif'
    ].join(';');

    const box = document.createElement('div');
    box.style.cssText = [
        'background:#1a1d27','border:1px solid #4f7cff','border-radius:12px',
        'padding:28px 32px','max-width:480px','width:90%',
        'box-shadow:0 20px 60px rgba(0,0,0,0.6)'
    ].join(';');

    const badge = document.createElement('div');
    badge.textContent = 'MODO DE TESTE — PONTO TOLENTX';
    badge.style.cssText = 'font-size:10px;font-weight:700;letter-spacing:1px;color:#4f7cff;margin-bottom:12px;';

    const desc = document.createElement('p');
    desc.textContent = description;
    desc.style.cssText = 'color:#e2e8f0;font-size:15px;margin:0 0 24px;line-height:1.5;';

    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;gap:12px;justify-content:flex-end;';

    const btnCancel = document.createElement('button');
    btnCancel.textContent = 'Cancelar (ESC)';
    btnCancel.style.cssText = [
        'background:#7f1d1d','color:#fca5a5','border:none','border-radius:8px',
        'padding:10px 20px','font-size:13px','font-weight:600','cursor:pointer'
    ].join(';');
    btnCancel.onclick = () => { window.__dryRunResult = 'cancel'; overlay.remove(); };

    const btnConfirm = document.createElement('button');
    btnConfirm.textContent = 'Confirmar (Enter)';
    btnConfirm.style.cssText = [
        'background:#15803d','color:#bbf7d0','border:none','border-radius:8px',
        'padding:10px 20px','font-size:13px','font-weight:600','cursor:pointer'
    ].join(';');
    btnConfirm.onclick = () => { window.__dryRunResult = 'confirm'; overlay.remove(); };

    document.addEventListener('keydown', function handler(e) {
        if (e.key === 'Enter') { window.__dryRunResult = 'confirm'; overlay.remove(); document.removeEventListener('keydown', handler); }
        if (e.key === 'Escape') { window.__dryRunResult = 'cancel'; overlay.remove(); document.removeEventListener('keydown', handler); }
    });

    btnRow.appendChild(btnCancel);
    btnRow.appendChild(btnConfirm);
    box.appendChild(badge);
    box.appendChild(desc);
    box.appendChild(btnRow);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    btnConfirm.focus();
}
"""

_HIGHLIGHT_JS = """
(selector) => {
    const el = document.querySelector(selector);
    if (!el) return false;
    el.style.outline = '3px solid #f59e0b';
    el.style.outlineOffset = '3px';
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return true;
}
"""


class DryRunAborted(Exception):
    pass


def detect_chrome_profiles() -> list[dict]:
    """
    Returns a list of available Chrome profiles on this machine.
    Each entry: {"user_data_dir": str, "profile_name": str, "label": str}
    """
    import os
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    user_data_base = Path(local_app_data) / "Google" / "Chrome" / "User Data"

    if not user_data_base.exists():
        return []

    profiles = []
    if (user_data_base / "Default").exists():
        profiles.append({
            "user_data_dir": str(user_data_base),
            "profile_name": "Default",
            "label": "Default",
        })

    for item in sorted(user_data_base.iterdir()):
        if item.is_dir() and item.name.startswith("Profile "):
            prefs_path = item / "Preferences"
            display_name = item.name
            if prefs_path.exists():
                try:
                    import json
                    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
                    display_name = prefs.get("profile", {}).get("name", item.name)
                except Exception:
                    pass
            profiles.append({
                "user_data_dir": str(user_data_base),
                "profile_name": item.name,
                "label": display_name,
            })

    return profiles


def execute_punch(
    punch_type: str,
    schedule_id: int,
    dry_run: bool = False,
    log_callback: Callable[[str, bool], None] | None = None,
) -> None:
    """
    Executes or simulates a punch registration on Pontotel.

    dry_run=True: validates the full auth flow up to (but not including) the
    punch button click. Safe — no point is registered.

    log_callback(message, ok): called for each step when provided (used by
    headless trace mode to stream progress to the web interface).
    """
    if punch_type not in PUNCH_BUTTON_PATTERNS:
        if not dry_run:
            db.mark_schedule_error(schedule_id)
        raise ValueError(f"Unknown punch type: {punch_type}")

    email = db.get_config("email")
    senha = db.decrypt(db.get_config("senha_enc"))
    local_coletor = db.get_config("local_coletor")
    pin = db.decrypt(db.get_config("pin_enc"))
    browser = normalize_browser(db.get_config("browser_channel"))
    browser_label = get_browser_label(browser)
    user_data_dir = db.get_config(get_profile_config_key(browser)) or get_dedicated_profile_path(browser)
    profile_name = db.get_config("chrome_profile_name")
    headless = db.get_config("headless_mode") == "1"

    # Prevent using the browser's main User Data dir — it's always locked by a running personal instance
    if is_main_user_data_dir(user_data_dir, browser):
        user_data_dir = get_dedicated_profile_path(browser)

    # Dry-run always runs visually so the user can see the overlay
    if dry_run:
        headless = False

    if not all([email, senha, local_coletor, pin, user_data_dir]):
        if not dry_run:
            db.mark_schedule_error(schedule_id)
        raise RuntimeError(f"Credenciais ou caminho do perfil {browser_label} não configurados.")

    _log_step(
        log_callback,
        f"Iniciando {'teste' if dry_run else 'registro'} de ponto no {browser_label}: {PUNCH_LABEL.get(punch_type, punch_type)}",
        ok=True,
    )

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel=get_playwright_channel(browser),
            headless=headless,
            args=[f"--profile-directory={profile_name}"],
            no_viewport=True,
        )
        page = context.new_page()

        try:
            _log_step(log_callback, "Abrindo Pontotel...", ok=True)
            page.goto(PONTOTEL_URL)
            page.wait_for_load_state("networkidle", timeout=15000)
            _log_step(log_callback, "Página carregada.", ok=True)

            _handle_login(page, email, senha, dry_run, log_callback)
            _handle_collector(page, local_coletor, dry_run, log_callback)
            _handle_pin(page, pin, dry_run, log_callback)

            if dry_run:
                _dry_run_find_punch_button(page, punch_type, log_callback)
                _log_step(log_callback, "Dry-run concluído — todos os passos validados. Nenhum ponto foi registrado.", ok=True)
            else:
                _click_punch_button(page, punch_type)
                _finalize(page)
                actual_time = datetime.now().strftime("%H:%M")
                db.mark_schedule_done(schedule_id, actual_time)
                _log_step(log_callback, f"Ponto registrado às {actual_time}.", ok=True)

        except DryRunAborted:
            _log_step(log_callback, "Teste cancelado pelo usuário.", ok=False)
            raise

        except Exception as exc:
            _log_step(log_callback, f"Erro: {exc}", ok=False)
            if not dry_run:
                db.mark_schedule_error(schedule_id)
            raise RuntimeError(f"Falha ao registrar ponto '{punch_type}': {exc}") from exc

        finally:
            time.sleep(3)
            context.close()


def _log_step(callback: Callable | None, message: str, ok: bool = True) -> None:
    print(f"[punch] {'OK' if ok else 'ERR'} {message}")
    if callback:
        callback(message, ok)


def _inject_step_overlay(page, description: str) -> bool:
    """
    Injects a confirmation overlay into the Pontotel page.
    Returns True if the user confirmed, False if cancelled.
    """
    page.evaluate(_OVERLAY_JS, description)
    try:
        page.wait_for_function(
            "() => window.__dryRunResult !== null",
            timeout=120_000,
        )
        result = page.evaluate("() => window.__dryRunResult")
        return result == "confirm"
    except PlaywrightTimeoutError:
        return False


def _highlight_element(page, locator) -> bool:
    """Highlights a Playwright locator with a yellow outline without clicking it."""
    try:
        element = locator.first
        element.wait_for(timeout=8000)
        # Scroll into view and highlight via JS using the element handle
        element.evaluate("""el => {
            el.style.outline = '3px solid #f59e0b';
            el.style.outlineOffset = '3px';
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }""")
        return True
    except Exception:
        return False


def _handle_login(page, email: str, senha: str, dry_run: bool, log_callback: Callable | None) -> None:
    """Performs login if the login form is visible."""
    try:
        email_field = page.get_by_role("textbox", name="email")
        email_field.wait_for(timeout=5000)
        _log_step(log_callback, "Preenchendo e-mail...", ok=True)
        email_field.fill(email)

        if dry_run:
            confirmed = _inject_step_overlay(page, f'Próximo passo: clicar em "Próximo" para avançar com o e-mail preenchido.')
            if not confirmed:
                raise DryRunAborted()

        page.get_by_role("button", name="Próximo").click()
        page.wait_for_load_state()

        _log_step(log_callback, "Preenchendo senha...", ok=True)
        page.get_by_label("Senha").fill(senha)

        if dry_run:
            confirmed = _inject_step_overlay(page, 'Próximo passo: clicar em "Entrar" para autenticar.')
            if not confirmed:
                raise DryRunAborted()

        page.get_by_role("button", name="Entrar").click()
        page.wait_for_load_state()
        _log_step(log_callback, "Login realizado.", ok=True)

    except DryRunAborted:
        raise
    except PlaywrightTimeoutError:
        # Login form not shown — session already active
        _log_step(log_callback, "Sessão já ativa — login ignorado.", ok=True)


def _handle_collector(page, local_coletor: str, dry_run: bool, log_callback: Callable | None) -> None:
    """Fills collector name if the field is visible (first access or new device)."""
    try:
        collector_field = page.get_by_role("textbox", name="Nome do coletor *")
        collector_field.wait_for(timeout=5000)
        _log_step(log_callback, f"Preenchendo coletor: {local_coletor}...", ok=True)
        collector_field.fill(local_coletor)

        if dry_run:
            confirmed = _inject_step_overlay(page, f'Próximo passo: clicar em "Salvar" para registrar o coletor "{local_coletor}".')
            if not confirmed:
                raise DryRunAborted()

        page.get_by_role("button", name="Salvar").click()
        page.wait_for_load_state()
        _log_step(log_callback, "Coletor registrado.", ok=True)

    except PlaywrightTimeoutError:
        _log_step(log_callback, "Coletor já registrado — etapa ignorada.", ok=True)


def _handle_pin(page, pin: str, dry_run: bool, log_callback: Callable | None) -> None:
    _log_step(log_callback, "Preenchendo PIN...", ok=True)
    pin_field = page.get_by_role("textbox", name="Pin de marcar ponto")
    pin_field.wait_for(timeout=10000)
    pin_field.fill(pin)

    if dry_run:
        confirmed = _inject_step_overlay(page, 'Próximo passo: clicar em "Confirmar" para validar o PIN e acessar a tela de registro.')
        if not confirmed:
            raise DryRunAborted()

    page.get_by_role("button", name="Confirmar").click()
    page.wait_for_load_state()
    time.sleep(1)
    _log_step(log_callback, "PIN confirmado — tela de registro acessada.", ok=True)


def _dry_run_find_punch_button(page, punch_type: str, log_callback: Callable | None) -> None:
    """
    Locates the punch type button and highlights it without clicking.
    This is the safe boundary of dry-run — registration never starts.
    """
    pattern = PUNCH_BUTTON_PATTERNS[punch_type]
    label = PUNCH_LABEL.get(punch_type, punch_type)
    _log_step(log_callback, f'Procurando botão "{label}" na tela de registro...', ok=True)

    locator = page.get_by_text(pattern)
    found = _highlight_element(page, locator)

    if found:
        _log_step(log_callback, f'Botão "{label}" encontrado e destacado. Dry-run encerrado — ponto NÃO registrado.', ok=True)
        if log_callback is None:
            # Visual mode: show final overlay informing the user
            _inject_step_overlay(
                page,
                f'Botão "{label}" encontrado e destacado em amarelo.\n\nDry-run concluído — nenhum ponto foi registrado.\n\nClique em Confirmar para fechar.',
            )
    else:
        _log_step(log_callback, f'Botão "{label}" NÃO encontrado. Verifique o fluxo.', ok=False)
        raise RuntimeError(f'Botão de ponto "{label}" não encontrado na página.')


def _click_punch_button(page, punch_type: str) -> None:
    pattern = PUNCH_BUTTON_PATTERNS[punch_type]
    page.get_by_text(pattern).click()


def _finalize(page) -> None:
    page.wait_for_load_state()
    page.get_by_role("button", name="Continuar sem foto").click()
    page.wait_for_load_state()
    page.get_by_role("button", name="Finalizar").click()
    # Hold until server confirms the punch before closing
    time.sleep(20)
