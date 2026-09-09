"""Verificação de disponibilidade de anúncios já coletados.

Os scrapers (`scraper.py`, `scraper_imovirtual.py`) nunca revisitam um link
que já esteja no histórico, então nunca percebem sozinhos quando um anúncio
sai do ar — arrendado ou removido pelo anunciante. Este módulo reconsulta os
anúncios já guardados e remove definitivamente (via `Storage.remover_resultado`)
os que já não estão disponíveis. O histórico de links visitados não é
alterado, então o scraper continua sem revisitar esse anúncio no futuro.

A verificação em si (checar se a página indica que o anúncio acabou) é
genérica entre fontes. Só uma coisa é específica por site: aproveitando que
a página já está aberta mesmo, também preenchemos a localização (`lat`/`lon`
pro mapa) de anúncios que ainda não têm — coletados antes dessa
funcionalidade existir, ou cuja geocodificação falhou da primeira vez —
reaproveitando as mesmas funções `extrair_localizacao_pagina` de cada
scraper (ver `_EXTRATORES_LOCALIZACAO`).
"""
from __future__ import annotations

import asyncio
import random
from typing import Callable

from playwright.async_api import async_playwright

import scraper
import scraper_imovirtual
from classificacao import detectar_anuncio_indisponivel
from storage import Storage, default_storage

TEMPO_ENTRE_VERIFICACOES = 2.0

_EXTRATORES_LOCALIZACAO = {
    "idealista": scraper.extrair_localizacao_pagina,
    "imovirtual": scraper_imovirtual.extrair_localizacao_pagina,
}


async def _anuncio_ainda_disponivel(page, url: str, store: Storage) -> bool:
    """Visita `url` e decide se o anúncio ainda está disponível.

    Falhas de rede/timeout não marcam o anúncio como indisponível — só uma
    confirmação positiva (404 ou texto de "já não disponível") o faz, para
    não perder anúncios reais por causa de uma instabilidade passageira.
    """
    try:
        resposta = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        store.log_mensagem(f"  -> Erro ao verificar {url}: {e}; mantendo como disponível.")
        return True

    if resposta is not None and resposta.status == 404:
        return False

    try:
        texto = await page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        texto = ""

    return not detectar_anuncio_indisponivel(texto)


async def verificar_disponibilidade(
    fonte: str,
    store: Storage | None = None,
    headless: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Revisita todos os anúncios já coletados de `fonte`.

    Como os que saem do ar são removidos (não só marcados), não há como um
    anúncio "já verificado" persistir na lista — a cada execução, todos os
    anúncios ainda guardados são candidatos a revisitar. Devolve a lista dos
    que foram removidos nesta execução (já removidos do storage antes do
    retorno).
    """
    store = store or default_storage
    a_verificar = [item for item in store.carregar_resultados(fonte) if item.get("link")]

    removidos: list[dict] = []
    if not a_verificar:
        return removidos

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--lang=pt-PT",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="pt-PT",
            timezone_id="Europe/Lisbon",
            ignore_https_errors=True,
        )
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        for i, item in enumerate(a_verificar, 1):
            link = item["link"]
            store.log_mensagem(f"[{i}/{len(a_verificar)}] Verificando disponibilidade: {link}")

            disponivel = await _anuncio_ainda_disponivel(page, link, store)
            if not disponivel:
                store.log_mensagem(f"  -> Removido da lista (arrendado ou fora do ar): {link}")
                store.remover_resultado(fonte, link)
                removidos.append(item)
            elif not item.get("localizacao"):
                extrator = _EXTRATORES_LOCALIZACAO.get(fonte)
                if extrator:
                    try:
                        localizacao = await extrator(page, store)
                    except Exception as e:
                        store.log_mensagem(f"  -> Erro ao geolocalizar {link}: {e}")
                        localizacao = None
                    if localizacao:
                        store.atualizar_localizacao(fonte, link, localizacao)

            if progress_callback:
                progress_callback(i, len(a_verificar))
            if i < len(a_verificar):
                await asyncio.sleep(TEMPO_ENTRE_VERIFICACOES + random.uniform(0.2, 1.0))

        await browser.close()

    return removidos
