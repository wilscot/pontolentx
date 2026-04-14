# Business Dependencies — PONTO TOLENTX 2.0

> Generated: 2026-04-14
> Scope: all files at project root (no `src/` directory exists)
> Method: full manual read of both source files before writing

---

## variable.py — Credential & Location Config

**Feeds:** `auto_ponto.py::run()` (imported directly: `from variable import email, senha, local, pin`)
**Fed by:** Manual edit by the operator (no dynamic loading, no env vars, no .env file)
**Business rules:**
- `email` — Pontotel login identity. Must match the registered employee account.
- `senha` — Plaintext password. Currently blank (`""`); must be filled before each use or the authentication step will fail silently (the login button is clicked regardless of value).
- `local` — Collector name (`"SETDIG"`). This string must exactly match a collector registered in the Pontotel account. A mismatch causes the "Salvar" step to fail or register the punch under the wrong location.
- `pin` — Employee PIN for punch confirmation. Currently blank (`""`); identical risk to `senha` — punch will attempt with empty PIN.

**Blast radius: High**
Changing any value here directly changes which employee account registers the punch and at which physical location. An incorrect `email`/`pin` logs in as the wrong person. An incorrect `local` registers the punch under a wrong or nonexistent collector.

---

## auto_ponto.py::run(playwright) — Full Punch Automation

**Feeds:** External system — Pontotel web app at `https://bateponto.pontotel.com.br/#/`
**Fed by:**
- `variable.py` (credentials/location/pin)
- `sys.argv[1]` (punch type selector — runtime argument)

**Business rules:**

1. **Authentication sequence is strictly ordered:**
   email field → "Próximo" → senha field → "Entrar" → collector name → "Salvar" → PIN field → "Confirmar". Any step failing (wrong credential, page load timeout) halts the entire punch without error recovery. There is no retry or fallback.

2. **Punch type is controlled exclusively by `sys.argv[1]`:**
   - `"entrada"` → clicks "Entrada" button
   - `"pausa"` → clicks "Pausa" button
   - `"retorno"` → clicks "Retorno" button
   - `"saida"` → clicks "Saída" button
   - **If `sys.argv[1]` is absent or any other value → no punch button is clicked.** The script continues (photo bypass + "Finalizar") but registers nothing meaningful. This is a silent no-op, not an error. **NEEDS CONFIRMATION:** Is the absence of an argument an intentional "dry run" mode or an unhandled edge case?

3. **Photo step is unconditionally bypassed:** `get_by_role("button", name="Continuar sem foto")` is always clicked. The system is assumed to never require a facial photo. If Pontotel ever enforces photo capture, this step breaks.

4. **`time.sleep(20)` after "Finalizar"** — a 20-second hold before the browser closes. Business intent: ensures the confirmation screen is fully rendered and the punch persists server-side before the session is destroyed. **NEEDS CONFIRMATION:** Is this value empirically derived or arbitrary? Reducing it could cause punches to not commit.

5. **Headless mode is commented out:** `# navegador = playwright.chromium.launch()` is disabled; the visible browser (`headless=False`) is the active mode. This means the script requires a graphical desktop session (cannot run in a headless server/CI context without code change).

**Blast radius: High**
This is the only executable module. All business logic (authentication, location selection, punch type routing, photo bypass, finalization) lives here. Any change to the UI flow on Pontotel's side breaks this script with no automated detection.

---

## Shared Data Contract

| Producer | Data | Consumers |
|---|---|---|
| `variable.py` (module-level variables) | `email`, `senha`, `local`, `pin` | `auto_ponto.py::run()` via direct import |
| `sys.argv[1]` (CLI caller) | punch type string | `auto_ponto.py::run()` — internal `if/elif` block |

**Contract risk:** `variable.py` exports bare strings (no types, no validation). If any value is `None` or non-string, the Playwright `.fill()` call raises a runtime error with no user-friendly message.

---

## Critical Hubs

| File/Function | Why Critical | Blast Radius |
|---|---|---|
| `variable.py` | Single source of all credentials and location config. Used without validation. | High |
| `auto_ponto.py::run()` | Sole business logic holder. Entire automation pipeline is a single linear function with no error handling. | High |

---

## Missing Infrastructure (noted, not assumed)

- No `docs/01-implantacao.md`, `02-customizacoes-frontend.md`, or `03-customizacoes-backend.md` exist yet.
- No `.env` or secrets management — credentials are hardcoded in `variable.py`.
- No logging — failures produce no output beyond unhandled exceptions.
- No scheduler — punch timing must be managed externally (Task Scheduler, cron, etc.).
