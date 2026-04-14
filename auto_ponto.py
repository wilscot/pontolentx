from variable import email, senha, local, pin
import re
from playwright.sync_api import Playwright, sync_playwright, expect
import time, sys

def run(playwright: Playwright) -> None:
    navegador = playwright.chromium.launch(headless=False)
    #navegador = playwright.chromium.launch()
    contexto = navegador.new_context()
    pagina = contexto.new_page()

    pagina.goto("https://bateponto.pontotel.com.br/#/")
    pagina.get_by_role("textbox", name="email").click()
    pagina.get_by_role("textbox", name="email").fill(email)
#    pagina.get_by_role("textbox", name="email").fill("etolentino@inovvati.com.br")
    pagina.get_by_role("button", name="Próximo").click()
    pagina.wait_for_load_state()
    pagina.get_by_label("Senha").click()
    pagina.get_by_label("Senha").fill(senha)
#    pagina.get_by_label("Senha").fill("Cr!st!n3")
    pagina.get_by_role("button", name="Entrar").click()
    pagina.wait_for_load_state()
    pagina.get_by_role("textbox", name="Nome do coletor *").click()
    pagina.get_by_role("textbox", name="Nome do coletor *").fill(local)
#    pagina.get_by_role("textbox", name="Nome do coletor *").fill("SETDIG")
    pagina.get_by_role("button", name="Salvar").click()
    pagina.wait_for_load_state()
    pagina.get_by_role("textbox", name="Pin de marcar ponto").click()
    pagina.get_by_role("textbox", name="Pin de marcar ponto").fill(pin)
#    pagina.get_by_role("textbox", name="Pin de marcar ponto").fill("03021977")
    pagina.get_by_role("button", name="Confirmar").click()
    #pagina.wait_for_load_state()
    #pagina.get_by_role("button", name="Sim, sou eu").click()
    pagina.wait_for_load_state()
    time.sleep(1)

    if len(sys.argv) > 1:
        # O primeiro argumento depois do nome do script
        argument = sys.argv[1]
        if argument == "entrada":
           # Botão de Entrada
           pagina.get_by_text(re.compile("Entrada", re.IGNORECASE)).click()
           #print("Entrada")
        elif argument == "pausa":
            # Botão de Pausa
            pagina.get_by_text(re.compile("Pausa", re.IGNORECASE)).click()
            #print("Pausa")
        elif argument == "retorno":
            # Botão de Retorno
            pagina.get_by_text(re.compile("Retorno", re.IGNORECASE)).click()
            #print("Retorno")
        elif argument == "saida":
            # Botão de Saída
            pagina.get_by_text(re.compile("Saída", re.IGNORECASE)).click()
            #print("Saída")

    pagina.wait_for_load_state()
    pagina.get_by_role("button", name="Continuar sem foto").click()
    pagina.wait_for_load_state()
    pagina.get_by_role("button", name="Finalizar").click()
    time.sleep(20)

with sync_playwright() as playwright:
    run(playwright)
