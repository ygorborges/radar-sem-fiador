from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import date
from typing import Callable
from playwright.async_api import async_playwright

import divisoes_administrativas
import geolocalizacao
from classificacao import (
    analisar_fiador,
    extrair_bloco_do_anuncio,
    extrair_tipo_anunciante,
    extrair_tipologia,
)
from storage import URL_BASE_DEFAULT, Storage, default_storage

FONTE = "idealista"

# Prefixos típicos de nomes de rua em Portugal. O idealista lista a
# localização do nível mais específico ao mais genérico (rua, bairro, zona,
# cidade); o primeiro item só é uma rua de verdade quando o anunciante
# revelou o endereço exato — quando não revela, o primeiro item já é o
# bairro. Ver `extrair_localizacao_pagina`.
_PREFIXOS_RUA = (
    "rua", "avenida", "av.", "praça", "praceta", "travessa", "largo",
    "alameda", "beco", "rotunda", "estrada", "calçada", "urbanização",
    "urbanizacao", "quinta", "impasse", "viela",
)

TEMPO_ENTRE_PAGINAS = 3.0
TEMPO_ENTRE_ANUNCIOS = 2.5
TEMPO_ANTES_PROXIMA_PAGINA = 1.5

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}


def extrair_data_atualizacao(texto: str | None, hoje: date | None = None) -> str | None:
    """Converte "Anúncio atualizado no dia 14 de Agosto" em "2026-08-14".

    O idealista não indica o ano nesse texto, então assume-se o ano corrente;
    se a data resultante cair no futuro (ex.: a virada do ano, analisando em
    janeiro um anúncio atualizado em dezembro), assume-se o ano anterior.
    """
    if not texto or not texto.strip():
        return None

    match = re.search(
        r"atualizad[oa]\s+no\s+dia\s+(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)",
        texto,
        re.IGNORECASE,
    )
    if not match:
        return None

    mes = MESES_PT.get(match.group(2).strip().lower())
    if not mes:
        return None

    hoje = hoje or date.today()
    try:
        data = date(hoje.year, mes, int(match.group(1)))
    except ValueError:
        return None

    if data > hoje:
        try:
            data = date(hoje.year - 1, mes, int(match.group(1)))
        except ValueError:
            return None

    return data.isoformat()


async def aceitar_cookies_se_possivel(page):
    seletores = [
        "button:has-text('Aceitar e fechar')",
        "button:has-text('Aceitar')",
        "text='Aceitar e fechar'",
        "text='Configurar'",
    ]

    for seletor in seletores:
        try:
            btn = page.locator(seletor).first
            if await btn.count() > 0:
                await btn.click(timeout=5000)
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            continue
    return False

async def extrair_dados_detalhe(page):
    """Extrai título, preço e descrição completa com fallback robusto."""
    tipos_alvo = {"Product", "SingleFamilyResidence", "Apartment", "RealEstateListing"}

    # 1) JSON-LD: tenta os formatos mais comuns e também listas de objetos
    try:
        scripts_json = await page.query_selector_all('script[type="application/ld+json"]')
        for script in scripts_json:
            try:
                conteudo = await script.inner_text()
                if not conteudo.strip():
                    continue

                dados = json.loads(conteudo)
                itens = dados if isinstance(dados, list) else [dados]
                for item in itens:
                    if not isinstance(item, dict):
                        continue

                    if item.get("@type") in tipos_alvo:
                        titulo = str(item.get("name", "")).strip()
                        descricao = str(item.get("description", "")).strip()
                        offers = item.get("offers", {})
                        if isinstance(offers, dict):
                            preco = str(offers.get("price", "N/A"))
                        else:
                            preco = "N/A"
                        if descricao:
                            return titulo or "Imóvel", preco, descricao

                    graph = item.get("@graph")
                    if isinstance(graph, list):
                        for node in graph:
                            if not isinstance(node, dict):
                                continue
                            if node.get("@type") in tipos_alvo:
                                titulo = str(node.get("name", "")).strip()
                                descricao = str(node.get("description", "")).strip()
                                offers = node.get("offers", {})
                                if isinstance(offers, dict):
                                    preco = str(offers.get("price", "N/A"))
                                else:
                                    preco = "N/A"
                                if descricao:
                                    return titulo or "Imóvel", preco, descricao
            except Exception:
                continue
    except Exception:
        pass

    # 2) Fallback por seletores mais tolerantes
    titulo_el = await page.query_selector("h1, .main-info__title-main, [data-testid='title']")
    titulo = (await titulo_el.inner_text()).strip() if titulo_el else ""
    if not titulo:
        try:
            titulo = (await page.title()).strip() or "Imóvel"
        except Exception:
            titulo = "Imóvel"

    preco_el = await page.query_selector(".info-data-price, .price-features__value, .details-price, [data-testid='price']")
    preco = (await preco_el.inner_text()).strip() if preco_el else "N/A"

    # 3) Fallback para o texto completo do corpo, que é mais robusto que "main" ou "detail-container"
    try:
        body_el = page.locator("body")
        descricao = (await body_el.inner_text()).strip()
    except Exception:
        descricao = ""

    if not descricao:
        try:
            descricao = await page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:
            descricao = ""

    if not descricao.strip():
        try:
            await aceitar_cookies_se_possivel(page)
            await page.wait_for_timeout(1500)
            descricao = await page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:
            descricao = ""

    descricao = extrair_bloco_do_anuncio(descricao)

    if not descricao.strip():
        return titulo or "Imóvel", preco, "BLOQUEADO_POR_ANTI_BOT"

    return titulo or "Imóvel", preco, descricao


async def extrair_data_atualizacao_pagina(page) -> str | None:
    """Lê o bloco de estatísticas do anúncio, que carrega de forma assíncrona."""
    try:
        el = await page.wait_for_selector(".stats-text", timeout=5000)
        texto = (await el.inner_text()).strip()
    except Exception:
        texto = None
    return extrair_data_atualizacao(texto)


async def extrair_tipo_anunciante_pagina(page) -> str | None:
    """Lê o rótulo "Particular"/"Profissional" exibido junto ao nome do anunciante.

    É a fonte de dados preferida (bem mais confiável que adivinhar a partir
    da descrição livre, ver `extrair_tipo_anunciante`); retorna None quando
    a página não expõe o elemento, para o chamador cair no fallback.
    """
    try:
        el = await page.wait_for_selector(".professional-name", timeout=5000)
        texto = (await el.inner_text()).strip()
    except Exception:
        texto = ""

    primeira_linha = texto.splitlines()[0].strip().lower() if texto else ""
    if "particular" in primeira_linha:
        return "Particular"
    if "profissional" in primeira_linha:
        return "Profissional"
    return None


def parece_endereco_de_rua(texto: str) -> bool:
    """Indica se `texto` parece um endereço de rua (vs. um nome de bairro/zona).

    Usado para decidir entre marcador (endereço preciso) e círculo (só a
    região) no mapa: um falso positivo faria um bairro parecer um endereço
    exato, e um falso negativo faria uma rua de verdade virar uma área
    aproximada maior do que precisa — nenhum dos dois é grave, só reduz um
    pouco a precisão visual do mapa.
    """
    texto_normalizado = (texto or "").strip().lower()
    return texto_normalizado.startswith(_PREFIXOS_RUA)


def _concelho_e_freguesia(itens: list[str]) -> tuple[str | None, str | None]:
    """Deduz concelho e freguesia a partir da hierarquia de localização do idealista.

    A freguesia é o penúltimo item da lista (do mais específico ao mais
    genérico). O concelho **não** vem do último item — que às vezes é uma
    string capenga tipo "Vila Nova de Gaia, Porto" (concelho e distrito
    grudados, quando o anúncio não é da cidade do Porto) — e sim derivado da
    freguesia pela divisão administrativa oficial
    (`divisoes_administrativas.concelho_da_freguesia`), a fonte confiável.
    Esse último item capenga ainda serve como pista de desempate quando a
    freguesia é ambígua (existe em mais de um concelho): mesmo não sendo um
    concelho "limpo", costuma conter o nome certo em algum lugar da string.
    Sem uma freguesia reconhecida (ou ambígua mesmo com a pista), o concelho
    fica `None` em vez de arriscar um valor errado.
    """
    if not itens or len(itens) < 2:
        return None, None
    freguesia_bruta = itens[-2]
    concelho = divisoes_administrativas.concelho_da_freguesia(freguesia_bruta, dica_cidade=itens[-1])
    freguesia = divisoes_administrativas.canonicalizar_freguesia(freguesia_bruta) if concelho else freguesia_bruta
    return concelho, freguesia


async def extrair_localizacao_pagina(page, store: Storage) -> dict | None:
    """Lê a hierarquia de localização do idealista e geocodifica o nível mais específico.

    O idealista nunca expõe a coordenada exata no HTML inicial (o
    `mapConfig.latitude`/`longitude` embutido na página vem sempre vazio) —
    só a lista textual em `#headerMap` (rua, bairro, zona, cidade, do mais
    específico ao mais genérico). Geocodificamos nós mesmos via Nominatim
    (`geolocalizacao.geocodificar_com_cache`). Devolve `None` quando não há
    lista de localização na página ou a geocodificação não encontra nada.
    """
    try:
        elementos = await page.query_selector_all("#headerMap .header-map-list")
        itens = [((await el.inner_text()) or "").strip() for el in elementos]
        itens = [texto for texto in itens if texto]
    except Exception:
        itens = []

    if not itens:
        return None

    texto = itens[0]
    concelho, freguesia = _concelho_e_freguesia(itens)
    preciso = parece_endereco_de_rua(texto)
    coords = None

    if concelho:
        # Com o concelho confirmado (via divisão administrativa oficial),
        # verifica a cidade do resultado em vez de confiar cegamente no
        # primeiro (ver docstring de `geolocalizacao.py` — nem busca
        # estruturada nem livre, sozinhas, bastam). Pra um endereço de rua
        # de verdade, tenta busca estruturada primeiro; se ela não confirmar
        # nada (rua ambígua/desconhecida da Nominatim), ou se não havia
        # endereço de rua pra começar, cai pra busca livre pela freguesia
        # (nível já confiável) — a busca estruturada não reconhece um nome
        # de freguesia com vírgulas como "rua".
        if preciso:
            coords = await asyncio.to_thread(
                geolocalizacao.geocodificar_com_cache, texto, store, concelho, True
            )
        if not coords and freguesia:
            coords = await asyncio.to_thread(
                geolocalizacao.geocodificar_com_cache, freguesia, store, concelho, False
            )
            preciso = False
    else:
        # Concelho não identificado — cai para a busca livre de sempre,
        # usando o último item da lista como pista de cidade (mesmo não
        # sendo um concelho "limpo", ver `_concelho_e_freguesia`), sem a
        # verificação de cidade (não há cidade confirmada pra verificar).
        cidade_para_busca = itens[-1] if len(itens) > 1 else ""
        endereco_busca = f"{texto}, {cidade_para_busca}, Portugal" if cidade_para_busca else f"{texto}, Portugal"
        coords = await asyncio.to_thread(geolocalizacao.geocodificar_com_cache, endereco_busca, store)

    if not coords:
        return None

    return {
        "lat": coords[0],
        "lon": coords[1],
        "preciso": preciso,
        "texto": texto,
        "concelho": concelho,
        "freguesia": freguesia,
    }


async def extrair_proxima_pagina(page):
    seletores = [
        "a[rel='next']",
        ".pagination a[aria-label*='Próxima']",
        ".pagination a[aria-label*='Siguiente']",
        ".pagination__item--next a",
        "a[title='Próxima página']",
        "a[title='Next page']",
        ".pagination .next a",
        ".pagination .pagination__next a",
    ]

    for seletor in seletores:
        try:
            link = page.locator(seletor).first
            if await link.count() == 0:
                continue
            href = await link.get_attribute("href")
            if href:
                return f"https://www.idealista.pt{href}" if href.startswith("/") else href
        except Exception:
            continue

    return None


async def raspar_idealista_porto(
    url_base: str | None = None,
    store: Storage | None = None,
    headless: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
):
    url_base = url_base or URL_BASE_DEFAULT
    store = store or default_storage
    historico = store.carregar_historico()

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
            permissions=["geolocation"],
            ignore_https_errors=True,
        )
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        links_imoveis = []
        url_atual = url_base
        max_paginas = 20

        for pagina in range(1, max_paginas + 1):
            store.log_mensagem(f"\n=== Página {pagina}: {url_atual} ===")
            await page.goto(url_atual, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            artigos = await page.query_selector_all("article.item")
            store.log_mensagem(f"Total de imóveis na página: {len(artigos)}")

            if pagina < max_paginas:
                atraso = TEMPO_ENTRE_PAGINAS + random.uniform(0.2, 1.2)
                store.log_mensagem(f"Aguardar {atraso:.1f}s antes da próxima página.")
                await asyncio.sleep(atraso)

            for artigo in artigos:
                titulo_el = await artigo.query_selector("a.item-link")
                if titulo_el:
                    link = await titulo_el.get_attribute("href")
                    link_completo = f"https://www.idealista.pt{link}" if link.startswith("/") else link
                    if link_completo not in historico:
                        links_imoveis.append(link_completo)

            proxima_pagina = await extrair_proxima_pagina(page)
            if not proxima_pagina or proxima_pagina == url_atual:
                store.log_mensagem("Sem mais páginas de resultados.")
                break

            url_atual = proxima_pagina

        # Todos os links já foram coletados; fecha a aba de listagem em vez de
        # deixá-la aberta e esquecida durante toda a fase de detalhe (que pode
        # levar dezenas de minutos).
        await page.close()

        anuncios_filtrados = []

        for i, url in enumerate(links_imoveis, 1):
            store.log_mensagem(f"[{i}/{len(links_imoveis)}] Analisando: {url}")
            historico.add(url)
            store.guardar_historico(historico)

            detalhe_page = await context.new_page()
            try:
                atraso_antes_detalhe = TEMPO_ANTES_PROXIMA_PAGINA + random.uniform(0.2, 1.3)
                store.log_mensagem(f"Aguardar {atraso_antes_detalhe:.1f}s antes do detalhe.")
                await asyncio.sleep(atraso_antes_detalhe)
                await detalhe_page.goto(url, wait_until="networkidle", timeout=20000)

                titulo, preco, descricao_completa = await extrair_dados_detalhe(detalhe_page)
                data_atualizacao = await extrair_data_atualizacao_pagina(detalhe_page)

                passou_filtro, status_match, trecho_status = analisar_fiador(descricao_completa)
                tipo_anunciante = (
                    await extrair_tipo_anunciante_pagina(detalhe_page)
                    or extrair_tipo_anunciante(descricao_completa)
                )

                store.log_mensagem(f"  -> CLASSIFICADO [{status_match}] [{tipo_anunciante}]: {titulo}")
                if trecho_status:
                    store.log_mensagem(f"     Trecho: {trecho_status[:180]}")

                item = {
                    "titulo": titulo,
                    "preco": preco,
                    "tipologia": extrair_tipologia(titulo, descricao_completa),
                    "tipo_anunciante": tipo_anunciante,
                    "status": status_match,
                    "trecho_status": trecho_status,
                    "link": url,
                    "descricao": descricao_completa,
                    "passou_filtro": passou_filtro,
                    "data_atualizacao": data_atualizacao,
                    "localizacao": await extrair_localizacao_pagina(detalhe_page, store),
                }
                anuncios_filtrados.append(item)
                # Guarda no disco assim que este anúncio é classificado, em vez
                # de só no final da varredura inteira — se o processo for
                # interrompido no meio, o que já foi analisado não se perde.
                store.atualizar_resultados(FONTE, [item])

            except Exception as e:
                store.log_mensagem(f"  -> Erro ao processar imóvel: {e}")
            finally:
                await detalhe_page.close()
                if progress_callback:
                    progress_callback(i, len(links_imoveis))
                if i < len(links_imoveis):
                    pausa = TEMPO_ENTRE_ANUNCIOS + random.uniform(0.3, 1.5)
                    store.log_mensagem(f"Pausa entre anúncios: {pausa:.1f}s")
                    await asyncio.sleep(pausa)

        await browser.close()
        return anuncios_filtrados

