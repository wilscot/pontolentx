# 02 — Customizações de Frontend — PONTO TOLENTX 2.0

---

### 2026-04-14 — Sessão 1: Interface Web Local (Implementação Inicial)

**Arquivos:** `templates/index.html`, `templates/setup.html`, `static/style.css`

**Stack:** HTML/CSS/JS puro servido pelo Flask (Jinja2 para renderização inicial, JS vanilla para atualizações dinâmicas). Sem framework frontend externo.

---

#### Tema Visual

Tema dark com as seguintes variáveis CSS base:

| Variável | Valor | Uso |
|---|---|---|
| `--bg` | `#0f1117` | Fundo geral da página |
| `--surface` | `#1a1d27` | Cards e superfícies de nível 1 |
| `--surface2` | `#21253a` | Inputs, superfícies de nível 2 |
| `--border` | `#2d3050` | Bordas gerais |
| `--text` | `#e2e8f0` | Texto principal |
| `--text-dim` | `#8892a4` | Texto secundário e labels |
| `--yellow` | `#f59e0b` | Destaque: botão Testar, highlights |

---

#### Tela Principal — index.html

**Visão semanal Seg-Sex:**
- Grid de 5 cards (um por dia), renderizados pelo Jinja2 no carregamento inicial
- Navegação entre semanas via botões seta: chama `GET /api/week/{week_start}` e re-renderiza o grid via JS (`renderWeek` / `renderDay`)
- Label da semana exibido como `YYYY-MM-DD — YYYY-MM-DD`

**Cards de dia:**
- Classes CSS dinâmicas: `is-today` (destaque azul), `is-past` (opacidade reduzida), `is-feriado` / `is-folga` / `is-facultativo` (fundo diferenciado)
- Cabeçalho: nome do dia em português (Segunda–Sexta) + data DD/MM
- Badge de tipo de dia no canto superior direito (clicável para abrir o modal de configuração)

**Badges de tipo de dia:**

| Tipo | Classe CSS | Cor |
|---|---|---|
| Normal | `day-badge` | neutro |
| Hoje | `today-badge` | azul |
| Feriado | `holiday-badge` | vermelho |
| Folga / Ponto facultativo | `folga-badge` | laranja |
| Meio expediente | `meio-badge` | roxo |

**Campos de horário editáveis inline:**
- `<input type="time">` exibido para pontos futuros com status `pendente`
- Ao alterar: botão "Salvar" aparece (classe `visible`); ao clicar ou pressionar Enter chama `PATCH /api/schedule/{id}`
- Pontos passados, registrados, com erro ou ignorados: exibidos como texto (não editáveis)
- Ponto registrado: exibe `actual_time` com classe `registered` (verde)
- Ponto com erro: exibe "Erro" com classe `error` (vermelho)
- Ponto ignorado: exibe `scheduled_time` com classe `ignored` (cinza)

**Barra de controle (scheduler-bar):**
- Indicador de status com ponto colorido (verde = ativo, cinza = inativo)
- Botão "Iniciar" / "Pausar" para o agendador
- Botão "Importar feriados" → `POST /api/holidays/import`
- Botão "Testar" (estilizado em amarelo) → abre modal de Dry-Run

---

#### Modal de Configuração de Dia

Abre ao clicar em qualquer badge de tipo de dia (exceto "Hoje"). Permite alterar o tipo do dia e, opcionalmente, adicionar uma observação.

**Opções de tipo de dia:**
- Normal — agenda os 4 pontos no horário programado
- Folga — nenhum ponto registrado
- Feriado — nenhum ponto registrado
- Ponto facultativo — nenhum ponto registrado
- Meio expediente — exibe campos adicionais de horário

**Campos de meio expediente (visíveis ao selecionar "Meio expediente"):**
- Entrada (padrão 07:30) e Saída (padrão 12:30)
- Apenas entrada e saída são agendadas; pausa e retorno não são gerados

Ao salvar: `POST /api/special-day` ou `DELETE /api/special-day/{date}` (para tipo "normal"), seguido de reload da semana atual.

---

#### Tela de Setup — setup.html

**Seções:**

1. **Credenciais:** campos para e-mail, senha (type=password) e PIN (type=password). Senha e PIN só são enviados se preenchidos — campos vazios preservam o valor anterior no banco.

2. **Perfil Chrome:** select populado com perfis detectados pelo backend (`detect_chrome_profiles()`). Exibe nome real do perfil lido do arquivo `Preferences`.

3. **Toggle Visual/Headless:** select com opções "Visual (janela aberta)" e "Headless (segundo plano)". Afeta apenas os punches reais do agendador — dry-run sempre usa visual.

4. **Horários base e ranges de randomização:** 4 linhas (Entrada, Pausa, Retorno, Saída), cada com:
   - Horário base (`type="time"`)
   - Range antes (minutos, `type="number"`)
   - Range depois (minutos, `type="number"`)

---

### 2026-04-14 — Sessão 2: Modal de Teste Dry-Run

**Arquivo:** `templates/index.html`

Modal dedicado ao dry-run com dois modos distintos de operação.

**Controles do modal:**
- Select "Tipo de ponto a simular": entrada / pausa almoço / retorno / saída
- Select "Modo do teste": Visual (passo a passo) / Headless (log ao vivo)

**Modo Visual:**
- Dispara `POST /api/test-run` com `mode="visual"`
- Chrome abre em janela visível; o overlay é injetado diretamente na página do Pontotel
- Hint informativo exibido no modal descrevendo o uso do overlay (botões Confirmar/Cancelar e atalhos Enter/Esc)
- Feedback via toast: "Chrome abrirá — confirme cada passo no overlay da página"

**Modo Headless:**
- Painel de log exibido no modal (fundo escuro, fonte monospace, scroll automático)
- `POST /api/test-run` com `mode="headless"` inicia o teste; resposta `{"started": true}` confirma início
- `EventSource('/api/test-run/stream')` recebe eventos SSE em tempo real
- Cada evento renderizado como linha colorida: verde com prefixo "check" para sucesso, vermelho com prefixo "x" para erro
- Evento `{"done": true}` encerra o EventSource e reabilita o botão "Iniciar teste"
- Timeout de 60s no servidor; erro de conexão SSE também reabilita o botão

**Controle de estado do botão:**
- Desabilitado e com texto "Executando..." enquanto o teste está em andamento
- Prevenção de duplo clique (backend retorna 409 se já há teste ativo)

**Toast notifications:**
- Função `toast(msg, type)` cria elemento temporário (3,5s) no container `#toast-container`
- Tipos: `success` (verde) e `error` (vermelho)
- Usadas em todas as ações assíncronas: salvar horário, atualizar dia, importar feriados

---

### 2026-04-14 — Sessão 3: Perfil Chrome Dedicado + Botão "Bater agora"

**Arquivos:** `templates/setup.html`, `templates/index.html`

---

#### setup.html — Perfil Chrome Dedicado

Seção "Perfil Chrome" reestruturada com duas opções de configuração inicial:

**Botão "Abrir Chrome para configurar"** (existente, mantido):
- Abre instância Playwright com o perfil dedicado via `POST /api/open-profile`
- Ao retornar `ok`, exibe botão "Fechar Chrome" e atualiza hint com instruções de login e registro de coletor
- `closeProfileSetup()` chama `POST /api/close-profile` e restaura UI ao estado inicial

**Botão "Importar sessão do Chrome"** (novo):
- Chama `POST /api/import-session`
- Copia cookies e Local Storage do perfil pessoal para o perfil de automação
- Feedback inline no hint: sucesso (verde) ou erro com instrução de fechar Chrome (vermelho)
- Ação mais rápida que o fluxo manual — indicada quando o usuário já tem sessão ativa no Chrome pessoal

Hint informativo atualizado para descrever as duas opções (Opção A: importar sessão / Opção B: abrir Chrome manual).

---

#### index.html — Botão "Bater agora"

Adicionado a cada linha de ponto **pendente do dia de hoje** nos cards da visão semanal.

Renderizado tanto no template Jinja2 (carga inicial) quanto na função JS `renderPunch` (navegação entre semanas via AJAX).

Comportamento:
- Exibe `confirm()` nativo antes de executar (ponto real, não dry-run)
- Desabilita o botão e exibe "..." durante a chamada
- Chama `POST /api/punch-now` com o `punch_type` da linha
- Em caso de sucesso: toast "Registro iniciado" + `location.reload()` após 25s (tempo para o Playwright concluir)
- Em caso de erro: toast com a mensagem do servidor + reabilita botão

**Botão "Iniciar" agendador — tratamento de erro:**
- `toggleScheduler()` envolto em try/catch
- Falha na requisição ou status não-ok exibe toast com mensagem de erro em vez de silenciar

---

### 2026-04-15 — Sessão 4: Home com 2 Semanas + Exibição Completa de Agendamento

**Arquivos:** `templates/index.html`, `static/style.css`

#### Nova composição da tela principal

- A home passou de 1 grade semanal para um bloco com **2 linhas**:
  - `Semana atual`
  - `Próxima semana`
- Navegação por setas mantém deslocamento de 7 dias, mas renderiza sempre o par de semanas (atual + próxima do bloco).
- Labels no topo foram divididas em duas linhas:
  - `#week-label-current`
  - `#week-label-next`

#### Exibição de horários (`Ag`/`Ex`)

- Todas as linhas de ponto mostram comparação direta:
  - `Ag: HH:MM · Ex: ...`
- Para pontos sem execução, `Ex` deixou de exibir `"Nulo"` e passou a exibir **traço**: `Ex: —`.
- Estados visuais mantidos:
  - `registered` (verde)
  - `error` (vermelho)
  - `ignored` (cinza riscado)
  - `not-executed` (amarelo)

#### Edição de horário pendente (novo fluxo)

- O pendente futuro não usa mais o `<input type="time">` como elemento principal de leitura.
- Fluxo novo:
  1. Exibe `Ag: HH:MM · Ex: —`
  2. Botão `Editar`
  3. Ao clicar, abre controles inline: `input time + Salvar + Cancelar`
- Após salvar:
  - Atualiza texto exibido sem recarregar (`Ag: novo_horario · Ex: —`)
  - Fecha modo de edição inline.

#### Renderização dinâmica via JS

- Substituição de `renderWeek(days)` único por:
  - `renderWeeksBlock(payload)` para o payload com duas semanas
  - `renderWeek(days, gridId)` para cada grade (`current` e `next`)
- `navigateWeek`, recarregamento pós `saveDayType` e pós `importHolidays` foram adaptados para atualizar as duas grades.

#### Responsividade CSS

- Breakpoints adicionados para grades:
  - até `1800px`: 3 colunas
  - até `1280px`: 2 colunas
  - até `768px`: 1 coluna + ajustes de paddings/header/scheduler-bar
