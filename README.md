# PONTO TOLENTX 2.0

Automatizador local de batida de ponto para a Pontotel, com interface web em Flask e launcher na bandeja do sistema no Windows.

## Fluxo Oficial no Windows

Em uma maquina nova, o caminho oficial e suportado e:

1. Baixar o projeto e extrair em uma pasta local.
2. Instalar as dependencias:

```bash
pip install -r requirements.txt
python -m playwright install chrome
```

3. Iniciar o sistema por:

```bat
start_pontolentx.cmd
```

Esse launcher:

- encontra `pythonw.exe`
- executa `tray_launcher.py` sem abrir console
- sobe o servico local
- abre o dashboard em `http://127.0.0.1:5000`

## Primeira Execucao

Na primeira execucao em uma maquina nova, o sistema deve:

- criar `data/ponto.db`
- criar `data/.secret.key`
- abrir o navegador no dashboard
- redirecionar para `/setup` se ainda nao houver configuracao

O icone principal aparece na bandeja do sistema do Windows.

## Arquivos Importantes

- `start_pontolentx.cmd`: entrada oficial no Windows
- `tray_launcher.py`: launcher da bandeja e controle do servico local
- `app.py`: aplicacao Flask
- `data/.secret.key`: chave local gerada automaticamente na primeira execucao

## O Que Nao E Mais Fluxo Oficial

O projeto nao usa mais:

- EXE versionado dentro de `dist/`
- artefatos versionados de `build/`
- script separado para build de launcher
- script separado apenas para criar atalho

O ponto de entrada unico e `start_pontolentx.cmd`.

## Observacoes

- Nao copie `data/.secret.key` entre maquinas.
- Se a chave mudar, credenciais criptografadas salvas deixam de ser validas.
- Para diagnostico, o launcher grava log em `data/launcher.log`.

## Referencias

- Guia de implantacao detalhado: [docs/01-implantacao.md](docs/01-implantacao.md)
- Historico tecnico de backend: [docs/03-customizacoes-backend.md](docs/03-customizacoes-backend.md)
