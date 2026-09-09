"""Verificação de disponibilidade de anúncios já coletados.

Os scrapers (`scraper.py`, `scraper_imovirtual.py`) nunca revisitam um link
que já esteja no histórico, então nunca percebem sozinhos quando um anúncio
sai do ar — arrendado ou removido pelo anunciante. Este módulo reconsulta os
anúncios já guardados e remove definitivamente (via `Storage.remover_resultado`)
os que já não estão disponíveis. O histórico de links visitados não é
alterado, então o scraper continua sem revisitar esse anúncio no futuro.

A verificação em si (checar se a página indica que o anúncio acabou) é
genérica entre fontes. Duas coisas são específicas por site, mas ambas
aproveitam que a página já está aberta mesmo, então cabem aqui em vez de
precisar de uma varredura nova:

1. Preencher (ou completar, se o formato mudou desde a última vez) a
   localização de anúncios que ainda não a têm por completo — reaproveitando
   as mesmas funções `extrair_localizacao_pagina` de cada scraper (ver
   `_EXTRATORES_LOCALIZACAO` e `_localizacao_incompleta`).
2. Trocar a descrição truncada em 250 caracteres (formato usado antes da
   descrição completa ser guardada) pela versão completa, reclassificando o
   anúncio em cima do texto novo — usando `extrair_dados_detalhe` de cada
   scraper (ver `_EXTRATORES_DESCRICAO` e
   `classificacao.descricao_parece_truncada`).
"""
from __future__ import annotations

import asyncio
import random
from typing import Callable

from playwright.async_api import async_playwright

import scraper
import scraper_imovirtual
from classificacao import analisar_fiador, descricao_parece_truncada, detectar_anuncio_indisponivel
from storage import Storage, default_storage

TEMPO_ENTRE_VERIFICACOES = 2.0

_EXTRATORES_LOCALIZACAO = {
    "idealista": scraper.extrair_localizacao_pagina,
    "imovirtual": scraper_imovirtual.extrair_localizacao_pagina,
}


async def _extrair_descricao_atual(fonte: str, page) -> str | None:
    """Reextrai a descrição completa da página atualmente aberta em `page`.

    Cada scraper devolve os dados de detalhe num formato diferente (tupla no
    idealista, dict no Imovirtual) — esta função normaliza os dois pro mesmo
    formato (só a descrição), que é tudo que a reclassificação precisa.
    """
    if fonte == "idealista":
        try:
            _, _, descricao = await scraper.extrair_dados_detalhe(page)
        except Exception:
            return None
        return descricao
    if fonte == "imovirtual":
        try:
            dados = await scraper_imovirtual.extrair_dados_detalhe(page)
        except Exception:
            return None
        return dados.get("descricao")
    return None


def _localizacao_incompleta(item: dict) -> bool:
    """Indica se falta preencher (ou completar) a localização de `item`.

    Cobre tanto quem nunca teve `localizacao` quanto quem já teve, mas num
    formato anterior a algum campo novo ter sido adicionado (ex.: `concelho`/
    `freguesia`, adicionados depois do campo `lat`/`lon` já existir) — sem
    isso, itens processados antes de uma mudança de esquema ficariam presos
    no formato antigo para sempre, já que só reprocessamos quem "não tem"
    localização.
    """
    localizacao = item.get("localizacao")
    return not localizacao or "concelho" not in localizacao


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
            else:
                if _localizacao_incompleta(item):
                    extrator_localizacao = _EXTRATORES_LOCALIZACAO.get(fonte)
                    if extrator_localizacao:
                        try:
                            localizacao = await extrator_localizacao(page, store)
                        except Exception as e:
                            store.log_mensagem(f"  -> Erro ao geolocalizar {link}: {e}")
                            localizacao = None
                        if localizacao:
                            store.atualizar_localizacao(fonte, link, localizacao)

                if descricao_parece_truncada(item.get("descricao")):
                    nova_descricao = await _extrair_descricao_atual(fonte, page)
                    if nova_descricao and not descricao_parece_truncada(nova_descricao):
                        passou_filtro, status, trecho = analisar_fiador(nova_descricao)
                        store.atualizar_descricao_e_classificacao(
                            fonte, link, nova_descricao, status, trecho, passou_filtro
                        )
                        store.log_mensagem(f"  -> Descrição completa recuperada e reclassificada: {link}")

            if progress_callback:
                progress_callback(i, len(a_verificar))
            if i < len(a_verificar):
                await asyncio.sleep(TEMPO_ENTRE_VERIFICACOES + random.uniform(0.2, 1.0))

        await browser.close()

    return removidos
