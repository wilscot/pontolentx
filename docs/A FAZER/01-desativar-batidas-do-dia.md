# 01 - Desativar batidas individuais do dia

## Objetivo

Permitir que o usuário desative individualmente qualquer batida de ponto de um dia presente ou futuro, sem transformar o dia inteiro em folga, feriado ou meio expediente.

Exemplo esperado: se o usuário desativar apenas `pausa` e `retorno`, o sistema deve manter `entrada` e `saida` ativas, agendadas e executáveis. Se o usuário desativar apenas uma batida, somente aquela batida deve ser ignorada.

Esta etapa deve ser concluída antes da etapa 02, porque as regras de jornada e almoço precisam saber quais batidas estão ativas.

## Escopo

Implementar somente a desativação/reativação individual de batidas.

Não implementar nesta etapa:

- Regras novas de 1h a 1h15 de almoço.
- Recalculo para fechar jornada entre 7h45 e 8h15.
- Aviso de edição manual com menos de 8h.
- Banco de horas manual.

## Arquivos prováveis

- `db.py`
- `app.py`
- `scheduler.py`
- `templates/index.html`
- `static/style.css`
- documentação em `docs/ai-log` somente se o usuário aprovar ao final

Impacto mapeado antes do plano:

- `db.py` e arquivo hub importado por `holidays.py`, `app.py`, `scheduler.py` e `punch.py`.
- `scheduler.py` e importado por `app.py`.
- Templates e CSS precisam de validação visual manual.

## Modelo de dados e comportamento

Usar o status existente `ignorado` para representar batida desativada pelo usuário.

Estados relevantes:

- `pendente`: batida ativa e ainda nao registrada.
- `registrado`: batida executada; nao pode ser desativada.
- `ignorado`: batida desativada pelo usuário; nao deve ter job ativo.
- `erro` e `nao_executado`: manter comportamento atual.

Regras obrigatórias:

- Desativar uma batida `pendente` deve mudar status para `ignorado`.
- Reativar uma batida `ignorado` deve voltar para `pendente`, preservar ou recriar `scheduled_time` e permitir novo job do scheduler se a data/hora ainda for futura.
- Nao permitir desativar batida `registrado`; retornar erro 409 ou equivalente.
- Batidas ignoradas nao entram em "Proximo ponto".
- Batidas ignoradas devem aparecer claramente no card como "Desativado" ou "Ex desativado".
- O fluxo de "Bater agora" nao deve aparecer para batida ignorada.
- A edicao manual de horario nao deve aparecer para batida ignorada ate ela ser reativada.

## API

Adicionar uma rota autenticada para alternar a ativacao da batida.

Contrato recomendado:

```http
PATCH /api/schedule/<entry_id>/active
Content-Type: application/json

{
  "active": false
}
```

Resposta de sucesso:

```json
{
  "ok": true,
  "id": 123,
  "status": "ignorado"
}
```

Para reativar:

```json
{
  "active": true
}
```

Regras da rota:

- Validar que a entrada existe.
- Recusar `registrado`.
- Ao desativar, chamar `scheduler.cancel_entry_job(entry_id)`.
- Ao reativar, voltar para `pendente` e chamar `scheduler.reschedule_entry(entry_id)` se o scheduler estiver ativo.
- Depois do sucesso, o frontend deve atualizar o dashboard via `refreshDashboard()`.

## Banco

Adicionar funcoes pequenas em `db.py`, por exemplo:

- `set_schedule_ignored(entry_id: int) -> None`
- `reactivate_schedule_entry(entry_id: int) -> None`

Essas funcoes devem atualizar apenas a linha alvo.

Nao apagar a linha da tabela `schedule`, porque a etapa 02 precisa enxergar que aquela batida existe mas esta desativada.

## Frontend

No card do dia, para cada batida pendente de dia presente/futuro:

- Manter botao "Editar".
- Manter "Bater agora" apenas para hoje.
- Adicionar acao "Desativar" na propria linha.

Para batida `ignorado`:

- Mostrar horario agendado com estado visual cinza/riscado ou texto claro.
- Exibir acao "Reativar" se o dia nao estiver no passado.
- Nao exibir "Editar" nem "Bater agora".

Como o template tem renderizacao inicial Jinja e renderizacao dinamica JS, atualizar os dois caminhos:

- Macro `render_day_card`.
- Funcao JS `renderPunch`.

Adicionar funcao JS recomendada:

```js
async function togglePunchActive(entryId, active) {
  const response = await fetch(`/api/schedule/${entryId}/active`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active }),
  });

  if (!response.ok) {
    toast(active ? "Erro ao reativar ponto" : "Erro ao desativar ponto", "error");
    return;
  }

  await refreshDashboard();
  toast(active ? "Ponto reativado" : "Ponto desativado", "success");
}
```

Pode usar `confirm()` antes de desativar com texto objetivo:

```text
Desativar esta batida? Ela nao sera registrada automaticamente.
```

## Scheduler

Garantir que:

- Jobs de batidas ignoradas sejam removidos ao desativar.
- Jobs nao sejam criados para status diferente de `pendente`.
- Reativar uma batida futura recrie o job.

Revisar:

- `scheduler.reschedule_entry`
- `scheduler.cancel_entry_job`
- `_load_pending_jobs_for_date`
- `_schedule_punch_job`

## Validacao

Rodar:

```powershell
python -m py_compile app.py db.py scheduler.py punch.py holidays.py browser_profiles.py
```

Testes manuais:

- Abrir dashboard com um dia futuro normal.
- Desativar somente `pausa`; confirmar que `entrada`, `retorno` e `saida` continuam ativas.
- Reativar `pausa`; confirmar que volta para `pendente`.
- Desativar `pausa` e `retorno`; confirmar que o proximo ponto ignora essas batidas.
- Tentar desativar uma batida `registrado`; confirmar que o sistema recusa.
- Com scheduler ativo, desativar uma batida futura de hoje e confirmar que ela nao executa automaticamente.

## Aceite

Esta etapa esta pronta quando:

- O usuário consegue desativar e reativar qualquer batida individualmente.
- O estado fica persistido no SQLite.
- Batidas desativadas nao geram job e nao entram como proximo ponto.
- Nenhum comportamento de feriado, folga, facultativo ou meio expediente foi quebrado.
- A documentacao da execucao foi registrada abaixo.

## Registro da execução

Agente executor deve preencher ao terminar:

- Data:
- Arquivos alterados:
- Resumo do que foi feito:
- Comandos de validacao executados:
- Riscos ou pendencias:
