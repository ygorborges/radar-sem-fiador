"""Scraper do Imovirtual — segunda fonte do RadarSemFiador.

Segue os mesmos princípios do scraper do idealista (`scraper.py`): navegador
com marcas de automação escondidas, atrasos aleatórios entre páginas e
anúncios, e histórico para nunca revisitar o mesmo anúncio duas vezes. A
extração de dados é mais simples aqui porque o Imovirtual expõe título,
descrição, preço, tipologia e tipo de anunciante de forma estruturada no
JSON-LD de cada anúncio (ver notas em `extrair_dados_detalhe`).
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import date
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import async_playwright

from classificacao import analisar_fiador, extrair_tipo_anunciante, extrair_tipologia
from storage import URL_BASE_DEFAULT_IMOVIRTUAL, Storage, default_storage

FONTE = "imovirtual"
BASE_URL = "https://www.imovirtual.com"

TEMPO_ENTRE_PAGINAS = 3.0
TEMPO_ENTRE_ANUNCIOS = 2.5
TEMPO_ANTES_PROXIMA_PAGINA = 1.5


def construir_url_pagina(url_base: str, pagina: int) -> str:
    """Ajusta (ou remove, para a página 1) o parâmetro `page` da URL de busca."""
    partes = urlsplit(url_base)
    query = dict(parse_qsl(partes.query))
    if pagina <= 1:
        query.pop("page", None)
    else:
        query["page"] = str(pagina)
    return urlunsplit((partes.scheme, partes.netloc, partes.path, urlencode(query), partes.fragment))


def extrair_numero_pagina_do_titulo(titulo: str) -> int:
    """Lê "Página 4 - ..." e devolve 4; sem esse prefixo, é a página 1.

    Importante: pedir uma página além da última existente não dá erro nem
    fica vazio — o Imovirtual simplesmente devolve a última página válida de
    novo. É por isso que a paginação em `raspar_imovirtual` confere o número
    real da página recebida (via esta função) em vez de só contar itens.
    """
    match = re.match(r"\s*P[áa]gina\s+(\d+)\s*-", titulo or "", re.IGNORECASE)
    return int(match.group(1)) if match else 1


def normalizar_href_anuncio(href: str) -> str:
    """Remove o prefixo "/hpr" de variantes promovidas do mesmo anúncio.

    O Imovirtual às vezes lista o mesmo anúncio duas vezes na mesma busca:
    uma vez no caminho normal ("/pt/anuncio/...") e outra com um prefixo de
    posição promovida/patrocinada ("/hpr/pt/anuncio/..."). A variante "/hpr"
    aponta pro mesmo imóvel mas devolveu 404 ao ser visitada diretamente
    (achado real durante testes). Normalizar para o caminho canônico antes
    de guardar/comparar evita visitar a variante quebrada e evita processar
    o mesmo anúncio duas vezes.
    """
    return re.sub(r"^/hpr(/pt/anuncio/)", r"\1", href)


def extrair_data_atualizacao(texto: str | None) -> str | None:
    """Converte "Última atualização: 8.09.2026" em "2026-09-08".

    Ao contrário do idealista, o Imovirtual inclui o ano — não há
    ambiguidade nem necessidade de adivinhar a virada de ano.
    """
    if not texto or not texto.strip():
        return None

    match = re.search(
        r"[úu]ltima atualiza[çc][ãa]o:?\s*(\d{1,2})\.(\d{1,2})\.(\d{4})",
        texto,
        re.IGNORECASE,
    )
    if not match:
        return None

    dia, mes, ano = (int(g) for g in match.groups())
    try:
        return date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def _extrair_do_json_ld(dados: dict) -> dict | None:
    """Procura, dentro de um documento JSON-LD, o nó Product/Apartment do anúncio."""
    grafo = dados.get("@graph") if isinstance(dados, dict) else None
    if not isinstance(grafo, list):
        return None

    for node in grafo:
        if not isinstance(node, dict):
            continue
        tipos = node.get("@type")
        tipos = tipos if isinstance(tipos, list) else [tipos]
        if "Product" not in tipos and "Apartment" not in tipos:
            continue

        titulo = str(node.get("name") or node.get("headline") or "").strip()
        descricao_html = str(node.get("description") or "")
        descricao = re.sub(r"<[^>]+>", " ", descricao_html)
        descricao = re.sub(r"\s+", " ", descricao).strip()

        offers = node.get("offers")
        preco_num = offers.get("price") if isinstance(offers, dict) else None
        preco = f"{preco_num:.0f} €/mês" if isinstance(preco_num, (int, float)) else "N/A"

        tipologia = "Indefinida"
        tipo_anunciante = "Desconhecido"
        for prop in node.get("additionalProperty") or []:
            if not isinstance(prop, dict):
                continue
            nome = str(prop.get("name") or "").strip().lower()
            valor = str(prop.get("value") or "").strip()
            if nome == "tipologia" and valor:
                tipologia = valor.upper()
            if nome == "tipo de anunciante" and valor:
                tipo_anunciante = valor.capitalize()

        if titulo and descricao:
            return {
                "titulo": titulo,
                "preco": preco,
                "descricao": descricao,
                "tipologia": tipologia,
                "tipo_anunciante": tipo_anunciante,
            }

    return None


async def extrair_dados_detalhe(page) -> dict:
    """Extrai título, preço, descrição, tipologia e tipo de anunciante.

    Fonte primária: o JSON-LD (`@graph`) da página, que no Imovirtual já traz
    tipologia e tipo de anunciante estruturados em `additionalProperty` — bem
    mais confiável do que adivinhar por regex a partir de texto livre (como é
    preciso fazer para o idealista). Só cai no fallback de texto livre se o
    JSON-LD estiver ausente ou malformado.
    """
    try:
        scripts = await page.query_selector_all('script[type="application/ld+json"]')
        for script in scripts:
            try:
                conteudo = await script.inner_text()
                if not conteudo.strip():
                    continue
                dados = json.loads(conteudo)
            except Exception:
                continue

            extraido = _extrair_do_json_ld(dados)
            if extraido:
                return extraido
    except Exception:
        pass

    # Fallback: JSON-LD ausente/malformado — lê diretamente da página.
    try:
        titulo_el = await page.query_selector("h1")
        titulo = (await titulo_el.inner_text()).strip() if titulo_el else ""
    except Exception:
        titulo = ""
    if not titulo:
        try:
            titulo = (await page.title()).strip() or "Imóvel"
        except Exception:
            titulo = "Imóvel"

    try:
        descricao = (await page.evaluate("() => document.body ? document.body.innerText : ''")).strip()
    except Exception:
        descricao = ""

    if not descricao:
        return {
            "titulo": titulo or "Imóvel",
            "preco": "N/A",
            "descricao": "BLOQUEADO_POR_ANTI_BOT",
            "tipologia": "Indefinida",
            "tipo_anunciante": "Desconhecido",
        }

    return {
        "titulo": titulo or "Imóvel",
        "preco": "N/A",
        "descricao": descricao,
        "tipologia": extrair_tipologia(titulo, descricao),
        "tipo_anunciante": extrair_tipo_anunciante(descricao),
    }


async def extrair_data_atualizacao_pagina(page) -> str | None:
    """Lê o texto "Última atualização: D.MM.AAAA" da secção de histórico."""
    try:
        el = await page.wait_for_selector("p:has-text('Última atualização')", timeout=5000)
        texto = (await el.inner_text()).strip()
    except Exception:
        texto = None
    return extrair_data_atualizacao(texto)


async def aceitar_cookies_se_possivel(page) -> bool:
    seletores = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Aceitar tudo')",
        "button:has-text('Aceitar')",
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


async def raspar_imovirtual(
    url_base: str | None = None,
    store: Storage | None = None,
    headless: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
):
    url_base = url_base or URL_BASE_DEFAULT_IMOVIRTUAL
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
            ignore_https_errors=True,
        )
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        links_imoveis: list[str] = []
        max_paginas = 20
        cookies_aceites = False

        for pagina in range(1, max_paginas + 1):
            url_pagina = construir_url_pagina(url_base, pagina)
            store.log_mensagem(f"\n=== Página {pagina}: {url_pagina} ===")
            try:
                await page.goto(url_pagina, wait_until="domcontentloaded")
            except Exception as e:
                # Quando só existe 1 página de resultados, pedir "page=2" pode
                # ser recusado pelo site em vez de simplesmente devolver a
                # última página válida (que é o que acontece com 2+ páginas).
                store.log_mensagem(f"Não foi possível abrir a página {pagina} ({e}); parando paginação.")
                break
            await page.wait_for_timeout(2000)

            if not cookies_aceites:
                cookies_aceites = await aceitar_cookies_se_possivel(page)

            titulo_pagina = await page.title()
            pagina_real = extrair_numero_pagina_do_titulo(titulo_pagina)
            if pagina_real != pagina:
                store.log_mensagem(
                    f"Página {pagina} não existe (o site devolveu a página {pagina_real}); parando paginação."
                )
                break

            hrefs = await page.eval_on_selector_all(
                "a[data-cy='listing-item-link']",
                "els => els.map(e => e.getAttribute('href'))",
            )
            novos_na_pagina = 0
            for href in hrefs:
                if not href:
                    continue
                href = normalizar_href_anuncio(href)
                link_completo = f"{BASE_URL}{href}" if href.startswith("/") else href
                if link_completo not in historico and link_completo not in links_imoveis:
                    links_imoveis.append(link_completo)
                    novos_na_pagina += 1
            store.log_mensagem(f"Total de anúncios na página: {len(hrefs)} ({novos_na_pagina} novos)")

            if pagina < max_paginas:
                atraso = TEMPO_ENTRE_PAGINAS + random.uniform(0.2, 1.2)
                store.log_mensagem(f"Aguardar {atraso:.1f}s antes da próxima página.")
                await asyncio.sleep(atraso)

        # Todos os links já foram coletados; fecha a aba de listagem em vez de
        # deixá-la aberta e esquecida durante toda a fase de detalhe (que pode
        # levar dezenas de minutos) — evita que ela sofra qualquer interação
        # externa (anúncios, scripts da própria página) sem nenhum propósito.
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
                # "networkidle" quase sempre expirava (~18% das páginas, medido em
                # execução real): o Imovirtual tem anúncios/scripts que mantêm
                # requisições em segundo plano indefinidamente, então a página
                # nunca fica "ociosa". O JSON-LD (fonte principal dos dados) já
                # vem no HTML inicial, então "domcontentloaded" basta.
                await detalhe_page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await detalhe_page.wait_for_timeout(1000)

                dados = await extrair_dados_detalhe(detalhe_page)
                data_atualizacao = await extrair_data_atualizacao_pagina(detalhe_page)

                passou_filtro, status_match, trecho_status = analisar_fiador(dados["descricao"])

                store.log_mensagem(f"  -> CLASSIFICADO [{status_match}] [{dados['tipo_anunciante']}]: {dados['titulo']}")
                if trecho_status:
                    store.log_mensagem(f"     Trecho: {trecho_status[:180]}")

                item = {
                    "titulo": dados["titulo"],
                    "preco": dados["preco"],
                    "tipologia": dados["tipologia"],
                    "tipo_anunciante": dados["tipo_anunciante"],
                    "status": status_match,
                    "trecho_status": trecho_status,
                    "link": url,
                    "descricao": dados["descricao"],
                    "passou_filtro": passou_filtro,
                    "data_atualizacao": data_atualizacao,
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
