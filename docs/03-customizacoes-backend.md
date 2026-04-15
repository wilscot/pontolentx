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

---

### 2026-04-14 — Sessão 3: Perfil Chrome Dedicado, Importação de Sessão, Punch Manual e Correções

**Arquivos:** `app.py`, `punch.py`, `scheduler.py`

---

#### Problema raiz: perfil Chrome bloqueado (exit code 21)

O Chrome só permite uma instância por `user_data_dir`. Quando a automação tentava usar o diretório principal (`%LOCALAPPDATA%\Google\Chrome\User Data`) com o Chrome pessoal aberto, o processo lançado via Playwright era imediatamente encerrado com exit code 21 (profile in use).

**Solução:** perfil dedicado em `data/chrome-profile/` separado do Chrome pessoal.

---

#### app.py — Proteção contra diretório principal do Chrome

Duas funções auxiliares adicionadas:

```python
def _dedicated_profile_path() -> str
def _is_main_chrome_dir(path: str) -> bool
```

`_is_main_chrome_dir` compara via `Path.resolve()` para lidar com variações de capitalização e separadores. Aplicada em três pontos:

1. **POST `/setup`**: se o campo `chrome_profile_path` contiver o diretório principal, substitui pelo dedicado antes de salvar no DB.
2. **GET `/setup`**: se o DB tiver o caminho errado, exibe o dedicado no formulário.
3. **POST `/api/open-profile`**: se o path resolvido for o principal, substitui pelo dedicado antes de lançar o Playwright.

---

#### app.py — POST `/api/open-profile` (Playwright-based)

Substituiu a abordagem anterior (`subprocess.Popen`) por `launch_persistent_context` do Playwright com o perfil dedicado. O Playwright passa `--remote-debugging-pipe` internamente, forçando um novo processo Chrome independente de qualquer instância já aberta.

Ciclo de vida do Chrome de configuração:
- Thread daemon lança `launch_persistent_context` com `headless=False`
- Abre `https://bateponto.pontotel.com.br/#/` automaticamente
- Mantém Chrome aberto via `threading.Event.wait(timeout=900)` (15 min)
- `POST /api/close-profile` sinaliza o evento para fechar
- `_setup_context` (global com lock) rastreia se há instância ativa — retorna 409 se já aberta

---

#### app.py — POST `/api/import-session`

Copia cookies e Local Storage do perfil pessoal do Chrome para o perfil de automação, permitindo reutilizar a sessão já autenticada no Pontotel sem novo login ou registro de coletor.

Arquivos copiados:
- `Default/Network/Cookies` (SQLite com tokens de sessão)
- `Default/Local Storage/` (armazenamento web)

Criptografia DPAPI dos cookies é compatível pois ambos os perfis estão no mesmo usuário Windows.

Requisito: Chrome deve estar **fechado** durante a cópia — `PermissionError` é tratado e retorna mensagem orientando o usuário a fechar o Chrome.

---

#### app.py — POST `/api/punch-now`

Endpoint para execução imediata de um ponto real (não dry-run) sem esperar o horário agendado.

Fluxo:
1. Busca a entrada de hoje na tabela `schedule` para o `punch_type` informado
2. Retorna 404 se não encontrada, 409 se já registrada
3. Chama `cancel_entry_job(entry["id"])` para remover o job do APScheduler (evita duplo registro)
4. Executa `execute_punch` em thread daemon
5. Retorna `{"started": true}` imediatamente

---

#### punch.py — Proteção contra diretório principal

Em `execute_punch`, após ler `chrome_profile_path` do DB, verifica se é o diretório principal do Chrome. Se for, substitui silenciosamente pelo caminho dedicado para evitar exit code 21.

---

#### scheduler.py — Correção de deadlock na inicialização

**Bug:** `start()` adquiria `_lock` e, dentro do mesmo bloco, chamava `_daily_setup()`, que por sua vez chamava `_schedule_punch_job()`, que tentava adquirir `_lock` novamente. Threading.Lock não é reentrante — deadlock garantido quando `scheduler_active == "1"` no boot.

**Fix:** `_daily_setup()` movida para fora do bloco `with _lock:` em `start()`.

---

#### scheduler.py — cancel_entry_job

```python
def cancel_entry_job(entry_id: int) -> None
```

Remove o job APScheduler identificado por `punch_{entry_id}` se existir. Usado pelo endpoint `punch-now` para garantir que o job automático não dispare após registro manual.

---

### 2026-04-14 — Sessão 4: Sistema de Autenticação Flask (Login/Logout)

**Arquivos:** `db.py`, `app.py`, `templates/login.html`, `templates/index.html`, `templates/setup.html`

---

#### db.py — Funções de Autenticação

Duas funções adicionadas ao final do arquivo:

- `setup_auth()` — semeia as credenciais iniciais (`wfrancischini` / `admin123`) na tabela `config` usando `werkzeug.security.generate_password_hash`. Operação idempotente via `INSERT OR IGNORE` — não sobrescreve senha existente em execuções subsequentes. Chamada dentro de `init_db()` para garantir execução automática na primeira inicialização.
- `check_credentials(username, password)` — lê o hash armazenado no DB e valida com `werkzeug.security.check_password_hash`. Retorna `True` apenas se usuário e senha conferem. Senha nunca é armazenada em texto plano.

---

#### app.py — Autenticação e Proteção de Rotas

**Imports adicionados:** `session` (Flask) e `functools.wraps`.

**`app.secret_key`:** configurado com os bytes da chave Fernet existente em `data/.secret.key` (`db.KEY_PATH.read_bytes()`), reutilizando infraestrutura de segurança já presente sem gerar nova dependência.

**Decorator `login_required`:**
- Verifica se `session.get("logged_in")` é verdadeiro
- Redireciona para `GET /login` se não autenticado
- Aplicado a todas as 14 rotas existentes — acesso total para logado, redirect para deslogado (sem roles ou permissões granulares)

**Rotas adicionadas:**

| Método | Rota | Descrição |
|---|---|---|
| GET | `/login` | Renderiza `login.html` |
| POST | `/login` | Valida credenciais via `db.check_credentials`; define `session["logged_in"] = True` e redireciona para `/` em caso de sucesso; renderiza novamente com mensagem de erro em caso de falha |
| POST | `/logout` | Limpa a sessão com `session.clear()` e redireciona para `/login` |

---

#### templates/login.html

Novo template criado com tema dark consistente com o restante do app (fundo escuro, inputs e botão no padrão visual já utilizado). Exibe mensagem de erro inline quando as credenciais são rejeitadas.

---

#### templates/index.html e templates/setup.html

Botão "Sair" adicionado ao header de ambos os templates. Implementado como formulário `POST /logout` para garantir que o logout seja sempre um request POST (não navegável via GET/URL direta).

---

**Motivo da mudança:** proteger o app de acesso não autorizado em rede local, onde qualquer dispositivo na mesma rede poderia acessar a interface sem restrição.

---

### 2026-04-15 — Sessão 5: Horizonte de 4 Semanas + Recalculo Inteligente da Agenda

**Arquivos:** `db.py`, `scheduler.py`, `app.py`

#### db.py — Evolução de schema e comportamento de agenda

- Coluna `manual_override` adicionada na tabela `schedule`:
  - `0` = horário automático
  - `1` = horário ajustado manualmente pelo usuário
- Migração automática em runtime:
  - `_ensure_schedule_migrations(conn)` usa `PRAGMA table_info(schedule)` e executa `ALTER TABLE` quando necessário.
- `insert_schedule_entry(..., recalculate=False)` passou a operar como upsert controlado:
  - não toca em registros `status != 'pendente'`
  - não sobrescreve `manual_override=1`
  - com `recalculate=True`, atualiza apenas pendentes automáticos.
- `update_schedule_time` marca `manual_override=1` para preservar edição manual contra recálculos futuros.
- `mark_past_pending_as_not_executed(reference_date)` marca pendências passadas como `nao_executado`.
- `get_future_schedule_mondays(from_date)` retorna semanas futuras já existentes no banco para recálculo em lote.

#### scheduler.py — Janela rolante e recálculo automático

- Nova função central:
  - `ensure_schedule_horizon(anchor_date, weeks=4, recalc_week_start=None, recalculate_all=False)`
  - Mantém agenda de **4 semanas** (semana atual + 3 próximas).
- Regras de recálculo:
  - `weekly_generate` (segunda): recalcula a **próxima semana** (`recalculate_existing=True`).
  - `daily_setup` no dia 1º do mês: recalcula todas as 4 semanas do horizonte (`recalculate_all=True`), respeitando `manual_override`.
- Nova função:
  - `recalculate_future_schedule(from_date=None)`
  - Recalcula todas as semanas futuras já agendadas para o padrão atual do `/setup`, preservando manual e histórico.
  - Completa semanas ausentes até o horizonte de 4 semanas.
  - Se o scheduler estiver ativo, remapeia os jobs pendentes do dia atual (`_reschedule_pending_entries_for_date`).

#### app.py — API e setup alinhados ao novo motor

- `index()` passou a chamar `sched.ensure_schedule_horizon(today, weeks=4)` antes de montar a home.
- Payload da navegação semanal foi expandido:
  - `_build_two_weeks_data(week_start)` retorna:
    - `week_start`
    - `next_week_start`
    - `weeks` (lista com 2 semanas, cada uma com 5 dias)
- `GET /api/week/<week_start>` agora retorna esse payload de duas semanas.
- `POST /setup`:
  - detecta mudança real em `*_base`, `*_range_antes`, `*_range_depois`
  - quando houver mudança, chama `sched.recalculate_future_schedule(date.today())`.

---

### 2026-04-15 — Sessão 6: Ajuste de Exibição de Não Executado

**Arquivos:** `templates/index.html` (impacto funcional ligado ao payload backend já existente)

- A semântica de “não executado” permaneceu no backend (`status='nao_executado'`), mas a UI deixou de exibir texto `"Nulo"` e passou a exibir `Ex: —`.
- Nenhuma alteração de contrato API para esse ajuste visual.
