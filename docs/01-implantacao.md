# 01 — Implantação Inicial — PONTO TOLENTX 2.0

**Data:** 2026-04-14
**Status:** Produção local (Windows)

---

## Descrição do Projeto

Automatizador de batida de ponto para a plataforma web Pontotel (`https://bateponto.pontotel.com.br`). Executa os registros de forma autônoma via automação de browser (Playwright) com agendamento por APScheduler. Expõe uma interface web local via Flask para configuração e monitoramento.

---

## Stack

| Camada | Tecnologia |
|---|---|
| Servidor web | Flask >= 3.0.0 |
| Agendador | APScheduler >= 3.10.0 (BackgroundScheduler) |
| Automação de browser | Playwright >= 1.40.0, channel=chrome |
| Persistência | SQLite (via `sqlite3` nativo) |
| Criptografia | cryptography >= 42.0.0 (Fernet) |
| Feriados | requests >= 2.31.0 → BrasilAPI |
| Python | 3.11+ (union types nativos usados) |

---

## Estrutura de Arquivos

```
PONTO TOLENTX 2.0/
├── app.py              # Flask app, todas as rotas REST e abertura automática do browser
├── db.py               # Schema SQLite, criptografia Fernet, operações de dados
├── punch.py            # Automação Playwright: login, coletor, PIN, tipo de ponto
├── scheduler.py        # APScheduler: geração de agenda semanal, randomização, jobs
├── holidays.py         # Importação de feriados nacionais via BrasilAPI
├── requirements.txt    # Dependências pip
├── templates/
│   ├── index.html      # Tela principal: visão semanal Seg-Sex
│   └── setup.html      # Tela de configuração: credenciais, perfil Chrome, horários
├── static/
│   └── style.css       # Tema dark, componentes visuais
└── data/               # Gerado automaticamente na primeira execução
    ├── ponto.db        # Banco SQLite
    └── .secret.key     # Chave Fernet (gerada uma vez, nunca commitar)
```

---

## Como Executar

```bash
pip install -r requirements.txt
python -m playwright install chrome
python app.py
```

O Flask sobe em `http://127.0.0.1:5000` e o browser abre automaticamente após 1 segundo. Se o sistema ainda não estiver configurado (sem e-mail + senha), redireciona automaticamente para `/setup`.

---

## Banco de Dados

Arquivo: `data/ponto.db` (SQLite, criado automaticamente por `db.init_db()`).

### Tabelas

#### `config`
Configurações chave-valor do sistema.

| Coluna | Tipo | Descrição |
|---|---|---|
| key | TEXT PK | Nome da configuração |
| value | TEXT | Valor |

Chaves relevantes:

| Chave | Padrão | Descrição |
|---|---|---|
| email | "" | E-mail da conta Pontotel |
| senha_enc | "" | Senha encriptada com Fernet |
| pin_enc | "" | PIN de marcar ponto encriptado |
| local_coletor | "SETDIG" | Nome do coletor no Pontotel |
| chrome_profile_path | "" | Caminho do User Data do Chrome |
| chrome_profile_name | "Default" | Nome do perfil Chrome |
| headless_mode | "0" | "1" = headless, "0" = visual |
| scheduler_active | "0" | "1" = agendador ativo ao iniciar |
| entrada_base | "07:30" | Horário base de entrada |
| pausa_base | "11:30" | Horário base de pausa almoço |
| retorno_base | "12:30" | Horário base de retorno |
| saida_base | "16:30" | Horário base de saída |
| {tipo}_range_antes | "10" | Minutos antes do horário base para randomização |
| {tipo}_range_depois | "15" | Minutos depois do horário base para randomização |

#### `schedule`
Registros agendados de ponto.

| Coluna | Tipo | Descrição |
|---|---|---|
| id | INTEGER PK | Identificador |
| date | TEXT | Data ISO (YYYY-MM-DD) |
| punch_type | TEXT | entrada / pausa / retorno / saida |
| scheduled_time | TEXT | Horário agendado (HH:MM) |
| actual_time | TEXT | Horário real de execução |
| status | TEXT | pendente / registrado / erro / ignorado |

Constraint `UNIQUE(date, punch_type)` — apenas um registro por tipo por dia.

#### `special_days`
Dias especiais que alteram o comportamento padrão.

| Coluna | Tipo | Descrição |
|---|---|---|
| date | TEXT PK | Data ISO |
| day_type | TEXT | normal / feriado / folga / facultativo / meio_expediente |
| notes | TEXT | Observação (ex: nome do feriado) |
| custom_json | TEXT | JSON com horários customizados (meio expediente) |

---

## Credenciais Encriptadas

A chave Fernet é gerada na primeira execução e armazenada em `data/.secret.key`. Senha e PIN são encriptados com `db.encrypt()` antes de salvar no banco e descriptografados em memória apenas durante a execução do punch.

```
data/.secret.key  ← nunca commitar, nunca copiar entre máquinas
```

Trocar a chave invalida todas as senhas/PINs salvos — será necessário reconfigurar em `/setup`.

---

## Feriados via BrasilAPI

Endpoint utilizado: `https://brasilapi.com.br/api/feriados/v1/{ano}`

A função `import_current_and_next_year()` importa feriados do ano atual e do próximo. Dias já marcados com tipo diferente de `feriado` pelo usuário não são sobrescritos (override manual tem prioridade).

---

## Perfil Chrome

Detectado automaticamente via `%LOCALAPPDATA%/Google/Chrome/User Data`. A detecção lê o arquivo `Preferences` de cada perfil para exibir o nome real na tela de setup. O Playwright usa `launch_persistent_context` para reutilizar cookies e sessões existentes.

---

## Agendador

- **Timezone:** America/Sao_Paulo
- **Jobs fixos:** `daily_setup` (00:01 todo dia), `weekly_generate` (segunda-feira 00:02)
- **Jobs de ponto:** DateTrigger no horário exato de cada entrada agendada; `misfire_grace_time=300` (5 min de tolerância)
- **Persistência:** estado `scheduler_active` salvo no DB; ao reiniciar `app.py` o agendador é relançado automaticamente se estava ativo

---

## Randomização de Horários

Para cada tipo de ponto, o horário agendado é sorteado dentro do intervalo `[base - range_antes, base + range_depois]` em minutos. Anti-repetição: o minuto do sorteio não pode repetir o minuto do último registro do mesmo tipo de ponto no dia anterior, evitando padrão perceptível.

**Horários base padrão:**

| Tipo | Base |
|---|---|
| Entrada | 07:30 |
| Pausa almoço | 11:30 |
| Retorno | 12:30 |
| Saída | 16:30 |
