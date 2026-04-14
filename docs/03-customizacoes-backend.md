# 03 — Customizações de Backend — PONTO TOLENTX 2.0

---

### 2026-04-14 — Sessão 1: Sistema Completo (Implementação Inicial)

**Arquivos:** `db.py`, `punch.py`, `scheduler.py`, `holidays.py`, `app.py`

---

#### db.py

Schema SQLite com três tabelas (`config`, `schedule`, `special_days`) criadas via `init_db()`. Valores padrão inseridos com `INSERT OR IGNORE` para não sobrescrever configurações existentes ao reiniciar.

Criptografia Fernet: a chave é gerada uma única vez e salva em `data/.secret.key`. As funções `encrypt(value)` e `decrypt(value)` encapsulam o ciclo Fernet. `decrypt` retorna string vazia em caso de falha (evita crash por chave trocada).

Operações principais:
- `get_config` / `set_config` / `get_all_config` — leitura e escrita de configurações
- `is_configured()` — verifica se e-mail e senha estão presentes antes de renderizar a tela principal
- `insert_schedule_entry` / `update_schedule_time` / `mark_schedule_done` / `mark_schedule_error` / `mark_schedule_ignored` — ciclo de vida de um agendamento
- `get_previous_minute_for_type(punch_type, before_date)` — consulta o último minuto registrado para o tipo de ponto, usado pelo mecanismo anti-repetição
- `get_special_days_for_week` — retorna dicionário `{date: special_day}` para a semana completa em uma única query
- `delete_schedule_for_date` — remove apenas registros `status='pendente'`, preservando histórico de executados

---

#### punch.py

Automação Playwright usando perfil Chrome persistente (`launch_persistent_context`) com `channel="chrome"`. O perfil reutiliza cookies e sessões do Chrome real do usuário — login já salvo não é refeito.

Fluxo de `execute_punch(punch_type, schedule_id)`:
1. Abre `https://bateponto.pontotel.com.br/#/`
2. `_handle_login` — preenche e-mail + senha se o formulário estiver visível; caso contrário, sessão já ativa é reutilizada
3. `_handle_collector` — preenche nome do coletor se campo aparecer (ocorre em primeiro acesso ou novo dispositivo)
4. `_handle_pin` — preenche PIN e clica em "Confirmar"
5. `_click_punch_button` — localiza o botão do tipo de ponto por regex case-insensitive e clica
6. `_finalize` — clica em "Continuar sem foto" → "Finalizar" → aguarda 20s para confirmação do servidor

Padrões de localização dos botões por regex em `PUNCH_BUTTON_PATTERNS` para tolerância a variações de texto na UI do Pontotel.

---

#### scheduler.py

BackgroundScheduler com timezone `America/Sao_Paulo`.

Jobs fixos ao iniciar:
- `daily_setup` (CronTrigger 00:01): garante que os jobs do dia atual estejam carregados
- `weekly_generate` (CronTrigger segunda-feira 00:02): gera agenda da semana se não existir

Geração de agenda (`generate_week_schedule`):
- Itera Seg-Sex
- Dias `feriado`, `folga`, `facultativo`: sem entradas
- Dias `meio_expediente`: `_generate_half_day_entries` usa `custom_json` para horários e tipos de ponto customizados (padrão: apenas entrada e saída)
- Dias normais: `_generate_full_day_entries` com randomização por `_random_time`

Randomização (`_random_time`): sorteia dentro de `[base - range_antes, base + range_depois]`. Anti-repetição: remove da lista de candidatos qualquer minuto igual ao do último registro do mesmo tipo, evitando padrão perceptível em dias consecutivos.

`reschedule_entry(entry_id)`: chamado pelo endpoint `PATCH /api/schedule/:id` quando o usuário edita horário manualmente — remove job existente e cria novo com DateTrigger.

`misfire_grace_time=300`: tolerância de 5 minutos para jobs que atrasaram (ex: máquina em sleep).

---

#### holidays.py

Importa feriados nacionais via `https://brasilapi.com.br/api/feriados/v1/{ano}`. A função `import_current_and_next_year()` importa o ano atual e o próximo em sequência. Falhas de rede por ano são silenciadas individualmente (RequestException capturada) para não bloquear o outro ano.

Regra de prioridade: dias já marcados com tipo diferente de `feriado` pelo usuário não são sobrescritos.

---

#### app.py

Flask app com as seguintes rotas REST:

| Método | Rota | Descrição |
|---|---|---|
| GET | `/` | Tela principal; redireciona para `/setup` se não configurado |
| GET/POST | `/setup` | Configuração de credenciais e preferências |
| POST | `/api/scheduler/start` | Inicia o agendador |
| POST | `/api/scheduler/stop` | Para o agendador |
| GET | `/api/scheduler/status` | Status do agendador |
| PATCH | `/api/schedule/<id>` | Atualiza horário de um agendamento |
| POST | `/api/special-day` | Define tipo de dia especial |
| DELETE | `/api/special-day/<date>` | Remove tipo especial e regenera agenda normal |
| POST | `/api/holidays/import` | Importa feriados via BrasilAPI |
| GET | `/api/week/<week_start>` | Retorna dados da semana (gera se ausente) |

Abertura automática do browser: thread daemon com `time.sleep(1)` antes de `webbrowser.open("http://localhost:5000")`.

Ao iniciar (`__main__`): `db.init_db()` → relança agendador se `scheduler_active == "1"` → abre browser.

---

### 2026-04-14 — Sessão 2: Headless Toggle + Modo de Teste Dry-Run

**Arquivos:** `db.py`, `punch.py`, `app.py`

---

#### db.py — Headless Toggle

Adicionada chave `headless_mode` ao `DEFAULT_CONFIG` com padrão `"0"` (modo visual). Valor `"1"` ativa headless nos punches reais do agendador.

---

#### punch.py — Dry-Run e Overlay de Confirmação

Assinatura de `execute_punch` ampliada:
```python
execute_punch(punch_type, schedule_id, dry_run=False, log_callback=None)
```

**dry_run=True:**
- Executa o fluxo completo de autenticação (login → coletor → PIN)
- Para antes de clicar no botão de ponto — a fronteira segura é `_dry_run_find_punch_button`
- Destaca o botão encontrado com borda amarela (`_highlight_element`) sem clicar
- Nunca chama `db.mark_schedule_done` nem `db.mark_schedule_error`
- Força `headless=False` independente da configuração — o usuário precisa ver a janela

**Overlay de confirmação (_inject_step_overlay):**
- HTML/JS injetado via `page.evaluate(_OVERLAY_JS, description)` diretamente na página do Pontotel
- Fundo escuro semitransparente com caixa modal estilizada no tema dark do projeto
- Botões "Confirmar (Enter)" e "Cancelar (ESC)" com atalhos de teclado
- Aguarda `window.__dryRunResult` via `page.wait_for_function` com timeout de 120s
- Retorna `True` (confirmar) ou `False` (cancelar/timeout)

**Classe DryRunAborted:**
- Exception dedicada para aborto limpo quando o usuário cancela no overlay
- Propagada sem gerar erro de agendamento no DB

**_highlight_element(page, locator):**
- Localiza elemento via locator Playwright
- Aplica `outline: 3px solid #f59e0b` e `scrollIntoView` via JS no elemento
- Retorna bool indicando se o elemento foi encontrado

**log_callback(message, ok):**
- Callable opcional chamado a cada step do fluxo
- Usado pelo modo headless do test-run para transmitir progresso via queue ao SSE endpoint

**headless_mode:**
- Lido do DB em `execute_punch` e aplicado ao `launch_persistent_context`

---

#### app.py — Endpoints de Test-Run

**POST `/api/test-run`**

Aceita `{ punch_type, mode }`. Controle de concorrência via `_test_run_lock` + flag `_test_run_active` — retorna 409 se já há teste em andamento.

- `mode="headless"`: limpa a queue `_test_run_queue`, dispara thread daemon que chama `execute_punch(..., dry_run=True, log_callback=callback)`. O callback empurra dicts `{step, ok}` na queue; ao terminar empurra `None` como sentinel.
- `mode="visual"`: dispara thread daemon sem callback; o usuário interage com o overlay no Chrome. Não há stream de log.

**GET `/api/test-run/stream`**

SSE endpoint (Server-Sent Events, `text/event-stream`). Drena `_test_run_queue` com `timeout=60s`. Cada item é serializado como `data: {json}\n\n`. Sentinel `None` emite `{"done": true}` e encerra o stream. Header `X-Accel-Buffering: no` evita buffering por proxy nginx.

**headless_mode no POST `/setup`:**
Salvo via `db.set_config("headless_mode", "1" if data.get("headless_mode") == "1" else "0")`.
