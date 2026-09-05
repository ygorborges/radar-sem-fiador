import asyncio
import json
import random
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORICO_PATH = DATA_DIR / "historico_anuncios.json"
RESULTADOS_PATH = DATA_DIR / "resultados_idealista.json"
LOG_PATH = DATA_DIR / "scraper_log.txt"

URL_BASE_DEFAULT = "https://www.idealista.pt/areas/arrendar-casas/com-preco-max_999,tamanho-min_60,apartamentos,t1,t2,t3,t4-t5,arrendamento-longa-duracao/?shape=%28%28_tdzFp%7Cxs%40goBglAaC%7BhFvz%40ceCbpBmEdyE%7Ci%40xPjzB%7DbAb%7C%40c%7BAlSkc%40vlDc_B%60%5D%29%29&ordem=precos-asc"

TEMPO_ENTRE_PAGINAS = 3.0
TEMPO_ENTRE_ANUNCIOS = 2.5
TEMPO_ANTES_PROXIMA_PAGINA = 1.5

PADROES_EXPLICITOS = [
    r"sem fiador",
    r"sem necessidade de fiador",
    r"dispensa.*fiador",
    r"não exijo fiador",
    r"nao exijo fiador",
    r"substitu[íi]vel por cau[çc][ãao]",
    r"\d+\s*meses de cau[çc][ãao]",
    r"\d+\s*rendas adiantadas",
    r"cau[çc][ãao] refor[çc]ada",
    r"refor[çc]o de cau[çc][ãao]"
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
    texto_total = f"{titulo} {texto or ''}".lower()

    padroes = [
        r"\b(?:apartamento|casa|moradia|studio|loft|imóvel|imovel)\s*(?:t|tipo)?\s*(t?\d+[a-z]?)\b",
        r"\b(t\d+[a-z]?)\b",
        r"\b(\d+[a-z]?)\b",
    ]

    for padrao in padroes:
        match = re.search(padrao, texto_total, re.IGNORECASE)
        if not match:
            continue

        valor = (match.group(1) or match.group(2) or "").strip().lower()
        valor = valor.replace("tipo ", "").replace(" ", "")

        if valor.startswith("t"):
            valor_normalizado = valor.upper()
            if re.match(r"^T\d+[A-Z]?$", valor_normalizado):
                return valor_normalizado

        if re.match(r"^\d+[a-z]?$", valor):
            return f"T{valor.rstrip('abcdefghijklmnopqrstuvwxyz').upper()}"

        if re.match(r"^t\d+[a-z]?$", valor):
            return valor.upper()

    return "Indefinida"


def extrair_tipo_anunciante(texto: str) -> str:
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

def carregar_historico() -> set[str]:
    if not HISTORICO_PATH.exists():
        return set()
    try:
        with HISTORICO_PATH.open("r", encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, list):
            return {str(item) for item in dados}
    except Exception:
        pass
    return set()


def guardar_historico(historico: set[str]) -> None:
    with HISTORICO_PATH.open("w", encoding="utf-8") as f:
        json.dump(sorted(historico), f, ensure_ascii=False, indent=2)


def guardar_resultados(resultados: list[dict]) -> None:
    with RESULTADOS_PATH.open("w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)


def log_mensagem(mensagem: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {mensagem}\n"
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(linha)
    print(mensagem)


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


async def raspar_idealista_porto(url_base: str | None = None):
    url_base = url_base or URL_BASE_DEFAULT
    historico = carregar_historico()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
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
            log_mensagem(f"\n=== Página {pagina}: {url_atual} ===")
            await page.goto(url_atual, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            artigos = await page.query_selector_all("article.item")
            log_mensagem(f"Total de imóveis na página: {len(artigos)}")

            if pagina < max_paginas:
                atraso = TEMPO_ENTRE_PAGINAS + random.uniform(0.2, 1.2)
                log_mensagem(f"Aguardar {atraso:.1f}s antes da próxima página.")
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
                log_mensagem("Sem mais páginas de resultados.")
                break

            url_atual = proxima_pagina

        anuncios_filtrados = []

        for i, url in enumerate(links_imoveis, 1):
            log_mensagem(f"[{i}/{len(links_imoveis)}] Analisando: {url}")
            historico.add(url)
            guardar_historico(historico)

            detalhe_page = await context.new_page()
            try:
                atraso_antes_detalhe = TEMPO_ANTES_PROXIMA_PAGINA + random.uniform(0.2, 1.3)
                log_mensagem(f"Aguardar {atraso_antes_detalhe:.1f}s antes do detalhe.")
                await asyncio.sleep(atraso_antes_detalhe)
                await detalhe_page.goto(url, wait_until="networkidle", timeout=20000)

                titulo, preco, descricao_completa = await extrair_dados_detalhe(detalhe_page)

                passou_filtro, status_match, trecho_status = analisar_fiador(descricao_completa)
                tipo_anunciante = extrair_tipo_anunciante(descricao_completa)

                log_mensagem(f"  -> CLASSIFICADO [{status_match}] [{tipo_anunciante}]: {titulo}")
                if trecho_status:
                    log_mensagem(f"     Trecho: {trecho_status[:180]}")

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
                })

            except Exception as e:
                log_mensagem(f"  -> Erro ao processar imóvel: {e}")
            finally:
                await detalhe_page.close()
                if i < len(links_imoveis):
                    pausa = TEMPO_ENTRE_ANUNCIOS + random.uniform(0.3, 1.5)
                    log_mensagem(f"Pausa entre anúncios: {pausa:.1f}s")
                    await asyncio.sleep(pausa)

        guardar_resultados(anuncios_filtrados)
        await browser.close()
        return anuncios_filtrados

async def main():
    log_mensagem(f"Iniciando scraping em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    resultados = await raspar_idealista_porto(URL_BASE_DEFAULT)
    log_mensagem(f"\n--- Resultados Filtrados: {len(resultados)} ---\n")
    for item in resultados:
        log_mensagem(f"Status: {item['status']}")
        log_mensagem(f"Imóvel: {item['titulo']}")
        log_mensagem(f"Preço: {item['preco']}")
        log_mensagem(f"Link: {item['link']}")
        log_mensagem(f"Trecho: {item['descricao']}")
        log_mensagem("-" * 50)

    log_mensagem(f"\nHistórico salvo em: {HISTORICO_PATH}")
    log_mensagem(f"Resultados exportados para: {RESULTADOS_PATH}")

    log_mensagem("\n=== OPORTUNIDADES ENCONTRADAS ===")
    if not resultados:
        log_mensagem("Nenhuma oportunidade encontrada nesta varredura.")
    else:
        for idx, item in enumerate(resultados, start=1):
            log_mensagem(f"\n[{idx}] {item['titulo']}")
            log_mensagem(f"    Preço: {item['preco']}")
            log_mensagem(f"    Status: {item['status']}")
            log_mensagem(f"    Link: {item['link']}")

    log_mensagem("\nProcesso concluído. Use a página web para consultar e filtrar os resultados.")

if __name__ == "__main__":
    asyncio.run(main())