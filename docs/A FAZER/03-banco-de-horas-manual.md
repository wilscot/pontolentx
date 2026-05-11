# 03 - Banco de horas manual oficial

## Objetivo

Permitir que o usuário cadastre manualmente o total oficial de banco de horas, alinhado ao aplicativo oficial da empresa.

O valor manual deve substituir o total exibido no card "Banco de horas" do dashboard. Os saldos diarios calculados localmente continuam aparecendo nos cards de dia como referencia, mas nao determinam mais o total oficial exibido no resumo.

Esta etapa deve ser executada depois das etapas 01 e 02. Antes de implementar, leia:

- `docs/A FAZER/01-desativar-batidas-do-dia.md`
- `docs/A FAZER/02-regras-jornada-e-almoco.md`

Confira o "Registro da execução" dos dois arquivos antes de alterar codigo.

## Escopo

Implementar somente cadastro, persistencia e exibicao do banco de horas manual.

Nao implementar nesta etapa:

- Sincronizacao com sistema externo.
- Historico de alteracoes do banco.
- Recalculo automatico acumulado a partir do valor manual.
- Novas regras de jornada ou desativacao de batidas.

## Arquivos prováveis

- `db.py`
- `app.py`
- `templates/setup.html`
- `templates/index.html`, se for necessario diferenciar texto/hint do card
- `static/style.css`, se for necessario ajuste visual
- documentação em `docs/ai-log` somente se o usuário aprovar ao final

Impacto mapeado antes do plano:

- `db.py` e arquivo hub importado por `holidays.py`, `app.py`, `scheduler.py` e `punch.py`.
- `app.py` monta os dados do dashboard e metricas.
- `/setup` salva configuracoes e ja e o lugar correto para um campo manual persistente.

## Modelo de dados

Adicionar configuracao persistida em `db.DEFAULT_CONFIG`:

```python
"manual_bank_minutes": "0"
```

Armazenar sempre em minutos inteiros como string, por compatibilidade com a tabela `config`.

Exemplos:

- `+02:30` -> `"150"`
- `-01:15` -> `"-75"`
- `00:00` -> `"0"`

## Interface em /setup

Adicionar campo na tela de configuracao para o banco oficial.

Local recomendado:

- Uma nova secao perto de "Agenda automatica", ou antes dela, chamada "Banco de horas".

Campo recomendado:

- Label: `Banco de horas oficial`
- Input texto com placeholder `+00:00` ou `-00:00`
- Hint: `Informe o saldo exibido no aplicativo oficial da empresa. Este valor substitui o total calculado localmente no dashboard.`

Formato aceito:

- `HH:MM`
- `+HH:MM`
- `-HH:MM`

Normalizar ao salvar:

- Sem sinal deve ser positivo.
- Minutos devem estar entre `00` e `59`.
- Horas podem ter uma ou mais casas.
- Valor vazio deve ser tratado como `0`.

Se o formato for invalido:

- Nao salvar.
- Renderizar `/setup` com mensagem de erro.
- Preservar os demais valores preenchidos no formulario.

## Backend

Adicionar helpers em `app.py` ou `db.py`:

- parse de label `+HH:MM` para minutos.
- formatacao de minutos para label humano ja usado no dashboard.

Preferencia:

- Reusar `_format_duration_human(total_minutes, include_plus=True)` em `app.py` para exibicao.
- Criar helper especifico para parse para nao misturar com `_time_to_minutes`, que representa horario do dia e nao duracao/saldo.

Atualizar `setup()`:

- Ler `manual_bank_balance` ou nome semelhante do formulario.
- Validar formato.
- Salvar em `db.set_config("manual_bank_minutes", str(minutes))`.

Atualizar `_build_dashboard_summary()`:

- Continuar calculando `worked_minutes`, `expected_minutes` e saldos diarios para os outros cards.
- Para a metrica "Banco de horas", usar `manual_bank_minutes` como fonte do valor exibido.
- O hint deve deixar claro que e valor oficial/manual.

Comportamento recomendado da metrica:

- Valor: `_format_duration_human(manual_bank_minutes, include_plus=True)`
- Hint positivo: `saldo oficial manual`
- Hint negativo: `saldo oficial manual`
- Accent:
  - positivo: `overtime`
  - negativo: `danger`
  - zero: `muted`

## Frontend

Em `templates/setup.html`:

- Exibir o valor atual formatado como `+HH:MM`, `-HH:MM` ou `00:00`.
- Usar input `type="text"` para aceitar sinal.

Em `templates/index.html`:

- Ajustar somente se o texto/hint vindo do backend nao for suficiente.

Em `static/style.css`:

- Reusar estilos existentes de `.form-group`, `.settings-section-card` e `.metric-accent-*`.
- Criar classe nova apenas se necessario.

## Validacao

Rodar:

```powershell
python -m py_compile app.py db.py scheduler.py punch.py holidays.py browser_profiles.py
```

Testes manuais:

- Salvar `+02:30` em `/setup` e confirmar que o dashboard mostra `+2h 30m`.
- Salvar `-01:15` e confirmar que o dashboard mostra `-1h 15m` com destaque negativo.
- Salvar `00:00` ou vazio e confirmar saldo zerado.
- Tentar salvar formato invalido como `2,30`, `abc`, `01:99`; confirmar erro e que nao salva.
- Confirmar que saldos diarios nos cards continuam aparecendo conforme batidas reais.
- Confirmar que os ajustes das etapas 01 e 02 continuam funcionando.

## Aceite

Esta etapa esta pronta quando:

- O usuário consegue cadastrar banco oficial manual em `/setup`.
- O valor fica persistido no SQLite via tabela `config`.
- O card "Banco de horas" usa o valor manual, nao o calculo da janela exibida.
- Formatos invalidos sao recusados com mensagem clara.
- A documentacao da execucao foi registrada abaixo.

## Registro da execução

Agente executor deve preencher ao terminar:

- Data:
- Arquivos alterados:
- Resumo do que foi feito:
- Comandos de validacao executados:
- Riscos ou pendencias:
