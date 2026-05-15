# 02 - Regras de almoço, jornada diária e aviso de edição manual

## Objetivo

Ajustar a geração e o recalculo dos horarios para respeitar tres regras:

1. Almoço sempre entre `1h00` e `1h15`.
2. Jornada automatica diaria sempre entre `7h45` e `8h15` de trabalho.
3. Edicao manual de horario deve avisar antes de salvar quando deixar o dia com menos de `8h00`, mostrando o total previsto.

Esta etapa depende da etapa 01. Antes de implementar, leia `docs/A FAZER/01-desativar-batidas-do-dia.md` e confira o registro da execução desse arquivo.

## Escopo

Implementar somente regras de horario, recalculo e aviso de edicao manual.

Nao implementar nesta etapa:

- Banco de horas manual.
- Mudancas adicionais de layout fora do necessario para o aviso.
- Novos tipos de dia alem dos existentes.

## Arquivos prováveis

- `scheduler.py`
- `db.py`
- `app.py`
- `punch.py`, se for necessario disparar recalculo apos batida registrada
- `templates/index.html`
- `templates/setup.html`
- `static/style.css`
- documentação em `docs/ai-log` somente se o usuário aprovar ao final

Impacto mapeado antes do plano:

- `scheduler.py` e importado por `app.py` e usa `db.py`.
- `db.py` e hub importado por `holidays.py`, `app.py`, `scheduler.py` e `punch.py`.
- `_build_day_balance` alimenta cards e metricas do dashboard.

## Regras de negócio

### Almoço

Quando `pausa` e `retorno` estiverem ativas no mesmo dia:

- `retorno` deve ser calculado a partir de `pausa`.
- Intervalo minimo: 60 minutos.
- Intervalo maximo: 75 minutos.
- A variacao configuravel atual nao pode gerar almoço menor que 1h.
- O range configuravel ainda pode influenciar `pausa`, mas `retorno` deve obedecer a regra `pausa + 60..75`.

### Jornada automática

Para dia com `entrada`, `pausa`, `retorno` e `saida` ativas:

```text
trabalho = (pausa - entrada) + (saida - retorno)
```

O sistema deve gerar ou recalcular `saida` para deixar `trabalho` entre `7h45` e `8h15`.

Para dia sem almoço ativo, com apenas `entrada` e `saida` ativas:

```text
trabalho = saida - entrada
```

O sistema deve gerar ou recalcular `saida` para deixar `trabalho` entre `7h45` e `8h15`.

Se houver outras combinacoes incompletas de batidas ativas, nao inventar regra agressiva. Manter horarios existentes e nao bloquear o usuario.

### Recalculo apos atraso real

Quando uma batida real for registrada com atraso ou adiantamento, o sistema deve recalcular as batidas futuras pendentes do mesmo dia quando isso for necessario para manter a jornada dentro de `7h45..8h15`.

Exemplo:

- Entrada estava agendada para `07:30`.
- Entrada real ocorreu `08:00`.
- O sistema deve ajustar a saida futura para compensar o atraso, respeitando almoço ativo e batidas desativadas.

Preservar:

- Batida `registrado`.
- Batida `ignorado`.
- Batida com `manual_override=1`, exceto se for a propria batida editada pelo usuario.
- Dias passados.

## Design tecnico recomendado

Adicionar helpers puros em `scheduler.py` para facilitar teste manual e reduzir risco:

- converter `HH:MM` para minutos.
- converter minutos para `HH:MM`.
- calcular minutos trabalhados previstos para uma combinacao de batidas.
- escolher alvo diario aleatorio entre `465` e `495` minutos.
- escolher almoço aleatorio entre `60` e `75` minutos.

Fluxo recomendado na geração de dia normal:

1. Gerar `entrada` usando `_random_time` atual.
2. Gerar `pausa` usando `_random_time` atual.
3. Gerar `retorno` como `pausa + random(60..75)`, evitando repetir minuto do dia anterior quando possível.
4. Gerar `saida` a partir do alvo diario:
   - `saida = retorno + (target_work_minutes - (pausa - entrada))`.
5. Inserir usando `db.insert_schedule_entry`.

Para dias com batidas desativadas pela etapa 01:

- Nao recalcular ou reativar linhas com status `ignorado`.
- Se almoço estiver desativado porque `pausa` e `retorno` estao ignorados, calcular `saida = entrada + target_work_minutes`.

## Aviso na edição manual

Atualizar o endpoint `PATCH /api/schedule/<entry_id>` para conseguir informar impacto da edicao.

Contrato recomendado:

```http
PATCH /api/schedule/<entry_id>
Content-Type: application/json

{
  "scheduled_time": "15:40",
  "force": false
}
```

Se a edicao deixar o total previsto abaixo de `8h00` e `force` nao for `true`, retornar:

```json
{
  "requires_confirmation": true,
  "worked_minutes": 455,
  "worked_label": "7h 35m",
  "message": "Com este ajuste, o dia ficara com 7h 35m registradas."
}
```

Com status HTTP recomendado: `409`.

O frontend deve:

- Receber `requires_confirmation`.
- Mostrar `confirm()` com o total previsto.
- Se o usuario confirmar, reenviar o PATCH com `force: true`.
- Se cancelar, manter o horario original e nao salvar.

O aviso confirmado pelo usuario deve valer apenas para edicao manual de horario no card, conforme decisao do usuario. Nao aplicar este aviso a desativacao de batida nem a meio expediente nesta etapa.

## Pontos de atenção

- O sistema usa renderizacao inicial Jinja e re-render JS via `/api/week/<week_start>`. Atualizar ambos se houver novos campos no payload.
- `_build_day_balance` hoje calcula saldo a partir de `actual_time`; a regra de aviso precisa calcular previsao a partir de `scheduled_time`, status e valor editado.
- `manual_override=1` deve continuar protegendo edicoes manuais contra recalculos automaticos futuros.
- O texto da tela `/setup` deve explicar que os ranges continuam existindo, mas almoço e jornada diaria tem travas de negocio.

## Validacao

Rodar:

```powershell
python -m py_compile app.py db.py scheduler.py punch.py holidays.py browser_profiles.py
```

Testes manuais:

- Gerar semana futura normal e conferir que todo almoço fica entre `1h00` e `1h15`.
- Conferir que todo dia normal gerado fecha entre `7h45` e `8h15`.
- Desativar `pausa` e `retorno` no dia, gerar/recalcular e confirmar que `entrada` + `saida` fecha entre `7h45` e `8h15`.
- Registrar ou simular uma entrada atrasada e confirmar que uma saida futura pendente e ajustada para compensar.
- Editar manualmente uma batida para deixar o dia com `7h59` ou menos e confirmar que aparece aviso com o total previsto.
- Cancelar o aviso e confirmar que nada foi salvo.
- Confirmar o aviso e confirmar que a edicao foi salva.
- Editar manualmente para total `8h00` ou mais e confirmar que salva sem aviso.

## Aceite

Esta etapa esta pronta quando:

- Almoço nunca fica abaixo de 1h nem acima de 1h15 na agenda automatica.
- Jornada automatica fica entre 7h45 e 8h15 quando ha dados suficientes.
- Atrasos reais sao compensados em batidas futuras pendentes do mesmo dia.
- Edicao manual abaixo de 8h avisa e mostra o total previsto antes de salvar.
- A documentacao da execucao foi registrada abaixo.

## Registro da execução

Status: efetivado com sucesso

- Data: 2026-05-12
- Agente executor: Codex nesta sessao
- Arquivos alterados:
  - `app.py`
  - `db.py`
  - `scheduler.py`
  - `templates/index.html`
  - `templates/setup.html`
  - `docs/A FAZER/02-regras-jornada-e-almoco.md`
- Resumo do que foi feito:
  - A geração automática de dias normais agora calcula `retorno` a partir de `pausa` com almoço entre 60 e 75 minutos.
  - A geração automática de `saida` agora fecha a jornada entre 7h45 e 8h15 quando há quatro batidas ativas.
  - Quando `pausa` e `retorno` estão `ignorado`, o cálculo passa a considerar jornada direta `entrada` -> `saida`, também entre 7h45 e 8h15.
  - O recálculo automático preserva batidas `registrado`, `ignorado` e `manual_override=1`.
  - Após uma batida real registrada, as batidas futuras pendentes do mesmo dia são recalculadas para compensar atraso ou adiantamento quando necessário.
  - O carregamento do dashboard agora reconcilia o dia atual antes de montar os cards, cobrindo casos em que uma batida já registrada não disparou o recálculo no momento exato.
  - Ao desativar ou reativar batidas pelo endpoint da etapa 01, o dia é recalculado para refletir a nova combinação de batidas ativas.
  - O endpoint `PATCH /api/schedule/<entry_id>` agora retorna confirmação obrigatória quando a edição manual deixaria o total previsto abaixo de 8h00.
  - O frontend trata a confirmação: cancelar mantém o horário original sem salvar; confirmar reenvia com `force: true`.
  - A tela `/setup` passou a explicar que os ranges continuam existindo, mas almoço e jornada têm travas de negócio.
- Comandos de validacao executados:
  - `python -m py_compile app.py db.py scheduler.py punch.py holidays.py browser_profiles.py`
  - Teste Python com banco temporario para geração de semana normal, validando almoço entre 1h00 e 1h15 e jornada entre 7h45 e 8h15.
  - Teste Python com banco temporario para dia com `pausa` e `retorno` em `ignorado`, validando jornada direta `entrada` -> `saida`.
  - Teste Python com banco temporario para entrada registrada com atraso, validando ajuste da `saida` pendente.
  - Teste Flask com banco temporario para confirmação de edição manual abaixo de 8h00: resposta 409, cancelamento sem persistir e confirmação com `force: true`.
  - Teste Python com banco temporario para preservar batidas `registrado`, `ignorado` e `manual_override=1` durante recálculo.
  - Teste Flask com banco temporario para desativar `pausa` e `retorno` via API e recalcular a jornada direta.
  - Teste Python com banco temporario reproduzindo `entrada 07:39`, `pausa 11:38`, `retorno real 13:03` e `saida agendada 16:31`, validando reconciliação do dashboard para saída entre `16:49` e `17:19`.
  - `git diff --check -- app.py db.py scheduler.py templates/index.html templates/setup.html`
- Riscos ou pendencias:
  - A validação visual no navegador foi tentada, mas o Playwright local ainda não encontra Chrome em `C:\Users\wfrancischini\AppData\Local\Google\Chrome\Application\chrome.exe`, mesmo bloqueio registrado na etapa 01.
  - `docs/ai-log` não foi atualizado nesta execução porque o plano exige aprovação explícita do usuário para esse registro.
