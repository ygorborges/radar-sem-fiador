import asyncio
import json
import random
import re
from datetime import date
from playwright.async_api import async_playwright

from storage import URL_BASE_DEFAULT, Storage, default_storage

TEMPO_ENTRE_PAGINAS = 3.0
TEMPO_ENTRE_ANUNCIOS = 2.5
TEMPO_ANTES_PROXIMA_PAGINA = 1.5

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

# Distância máxima (sem atravessar pontuação de fim de frase) tolerada entre
# um verbo de dispensa ("dispensa", "não exige"...) e a palavra "fiador",
# para casar frases como "o senhorio dispensa a apresentação de fiador" sem
# também casar um "dispensa"/"não" de outro assunto qualquer, em outra frase
# da página, com um "fiador" mencionado bem mais adiante — era exatamente
# esse o bug do padrão antigo "dispensa.*fiador", sem nenhum limite.
_JANELA_PROXIMIDADE_FIADOR = r"[^.!?]{0,40}"

PADROES_EXPLICITOS = [
    r"\bsem fiador\b",
    r"\bsem necessidade de fiador\b",
    r"\bsem exig[êe]ncia de fiador\b",
    # cobre "não exijo/exija" (1ª pessoa, forma irregular) e "não
    # exige/exigem/exigia/exigimos" (demais conjugações de "exigir") antes
    # de "fiador", com filler limitado à mesma frase.
    rf"\bn[ãa]o\s+exi[jg]\w*{_JANELA_PROXIMIDADE_FIADOR}\bfiador\b",
    # forma pós-posta: "fiador não é necessário/obrigatório"
    rf"\bfiador\b{_JANELA_PROXIMIDADE_FIADOR}\bn[ãa]o\s+(?:é|e|era)\s+(?:necess[áa]ri[oa]|obrigat[óo]ri[oa])\b",
    r"\bisent[oa]\s+de\s+fiador\b",
    r"\bfiador\s+(?:opcional|dispens[áa]vel)\b",
    rf"\bdispens\w*{_JANELA_PROXIMIDADE_FIADOR}\bfiador\b",
    r"\bsubstitu[íi]vel por cau[çc][ãa]o\b",
    r"\bcau[çc][ãa]o refor[çc]ada\b",
    r"\brefor[çc]o de cau[çc][ãa]o\b",
]

def limpar_texto_cookie_banner(texto: str) -> str:
    if not texto:
        return texto

    texto = re.sub(r"No idealista utilizamos cookies.*?política de cookies\.?", " ", texto, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r"Nós e os nossos fornecedores efetuamos o seguinte tratamento de dados:.*?\.", " ", texto, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def extrair_bloco_do_anuncio(texto: str) -> str:
    if not texto:
        return ""

    texto = limpar_texto_cookie_banner(texto)
    marcadores = [
        "Comentário do anunciante",
        "Descrição",
        "Condições de Arrendamento",
        "Observações",
        "Sobre o imóvel",
    ]

    menores = []
    for marcador in marcadores:
        idx = texto.find(marcador)
        if idx != -1:
            menores.append(idx)

    if menores:
        start = min(menores)
        return texto[start:].strip()

    return texto.strip()


def extrair_tipologia(titulo: str, texto: str) -> str:
    """Deduz a tipologia (T1, T2, ...) a partir do título e do texto do anúncio.

    Havia um 3º padrão de reserva que casava o primeiro número solto em
    qualquer parte do título/texto (ex.: o "60" de "Rua Tal, 60", ou o "2"
    de "a 2 minutos da estação"), virando "T60"/"T2" por engano. Sem um
    "Txx" explícito perto de uma palavra do tipo de imóvel, é mais seguro
    devolver "Indefinida" do que adivinhar a partir de um número qualquer.
    """
    texto_total = f"{titulo} {texto or ''}".lower()

    padroes = [
        r"\b(?:apartamento|casa|moradia|studio|loft|imóvel|imovel)\s*(?:t|tipo)?\s*(t?\d+[a-z]?)\b",
        r"\b(t\d+[a-z]?)\b",
    ]

    for padrao in padroes:
        match = re.search(padrao, texto_total, re.IGNORECASE)
        if not match:
            continue

        valor = match.group(1).strip()

        if valor.startswith("t"):
            valor_normalizado = valor.upper()
            if re.match(r"^T\d+[A-Z]?$", valor_normalizado):
                return valor_normalizado
        elif re.match(r"^\d+[a-z]?$", valor):
            return f"T{valor.rstrip('abcdefghijklmnopqrstuvwxyz').upper()}"

    return "Indefinida"


def extrair_tipo_anunciante(texto: str) -> str:
    """Adivinha o tipo de anunciante a partir do texto livre da descrição.

    É um fallback: o idealista expõe esse dado de forma estruturada no
    elemento ".professional-name" da página de detalhe (ver
    `extrair_tipo_anunciante_pagina`), que é bem mais confiável do que
    procurar as palavras "particular"/"profissional" soltas no texto —
    elas podem aparecer em frases sem relação nenhuma com o tipo de
    anunciante (ex.: "estacionamento particular", "acabamento profissional").
    Isto só é usado quando aquele elemento não é encontrado na página.
    """
    if not texto or not texto.strip():
        return "Desconhecido"

    texto_normalizado = " ".join(texto.split())
    padroes = [
        r"anunciante\s+(particular|profissional)",
        r"(particular|profissional)\s+anunciante",
        r"(particular|profissional)\s*(?:no|na|do|da)?\s*(?:anúncio|anuncio|imóvel|imovel)",
    ]

    for padrao in padroes:
        match = re.search(padrao, texto_normalizado, re.IGNORECASE)
        if match:
            valor = match.group(1).strip().lower()
            if "particular" in valor:
                return "Particular"
            if "profissional" in valor:
                return "Profissional"

    if re.search(r"\bparticular\b", texto_normalizado, re.IGNORECASE):
        return "Particular"
    if re.search(r"\bprofissional\b|\bimobiliária\b|\bagente\b", texto_normalizado, re.IGNORECASE):
        return "Profissional"
    return "Desconhecido"


def extrair_trecho_status(texto: str, padrao: str | None = None) -> str | None:
    if not texto or not texto.strip():
        return None

    texto_normalizado = " ".join(texto.split())
    if padrao:
        match = re.search(padrao, texto_normalizado, re.IGNORECASE)
        if not match:
            return None
        inicio = max(0, match.start() - 80)
        fim = min(len(texto_normalizado), match.end() + 220)
        return texto_normalizado[inicio:fim].strip()

    match = re.search(r"fiador", texto_normalizado, re.IGNORECASE)
    if not match:
        return None
    inicio = max(0, match.start() - 90)
    fim = min(len(texto_normalizado), match.end() + 220)
    return texto_normalizado[inicio:fim].strip()


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


def detectar_bloqueio_idealista(texto: str) -> bool:
    if not texto or not texto.strip():
        return False

    texto_lower = texto.lower()
    padroes_bloqueio = [
        "demasiados pedidos",
        "muitos pedidos",
        "aguarde uns momentos",
        "tente novamente",
        "ray id",
        "cloudflare",
        "captcha",
        "anti-bot",
        "too many requests",
        "blocked",
        "temporariamente indisponível",
        "do not share your credentials",
    ]
    return any(padrao in texto_lower for padrao in padroes_bloqueio)


def analisar_fiador(texto: str) -> tuple[bool, str, str | None]:
    if not texto or not texto.strip():
        return False, "ERRO_TEXTO_VAZIO", None

    texto = extrair_bloco_do_anuncio(texto)
    if not texto.strip():
        return False, "ERRO_TEXTO_VAZIO", None

    texto_lower = texto.lower()

    if detectar_bloqueio_idealista(texto):
        trecho = extrair_trecho_status(texto, r"demasiados pedidos|aguarde uns momentos|ray id|cloudflare|captcha|too many requests")
        return False, "BLOQUEADO_POR_ANTI_BOT", trecho or texto[:300]

    # 1. Verifica se há confirmação explícita de flexibilidade
    for padrao in PADROES_EXPLICITOS:
        trecho = extrair_trecho_status(texto, padrao)
        if trecho:
            return True, "CONFIRMADO (Explícito/Flexível)", trecho

    # 2. Verifica ausência TOTAL da palavra fiador
    if not re.search(r"fiador", texto, re.IGNORECASE):
        return True, "SEM MENÇÃO (Não cita fiador)", None

    trecho = extrair_trecho_status(texto)
    return True, "EXIGE FIADOR", trecho

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


async def raspar_idealista_porto(url_base: str | None = None, store: Storage | None = None, headless: bool = False):
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

                anuncios_filtrados.append({
                    "titulo": titulo,
                    "preco": preco,
                    "tipologia": extrair_tipologia(titulo, descricao_completa),
                    "tipo_anunciante": tipo_anunciante,
                    "status": status_match,
                    "trecho_status": trecho_status,
                    "link": url,
                    "descricao": descricao_completa[:250].replace("\n", " ") + "...",
                    "passou_filtro": passou_filtro,
                    "data_atualizacao": data_atualizacao,
                })

            except Exception as e:
                store.log_mensagem(f"  -> Erro ao processar imóvel: {e}")
            finally:
                await detalhe_page.close()
                if i < len(links_imoveis):
                    pausa = TEMPO_ENTRE_ANUNCIOS + random.uniform(0.3, 1.5)
                    store.log_mensagem(f"Pausa entre anúncios: {pausa:.1f}s")
                    await asyncio.sleep(pausa)

        store.atualizar_resultados(anuncios_filtrados)
        await browser.close()
        return anuncios_filtrados

