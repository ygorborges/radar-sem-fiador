"""Classificação de anúncios quanto à exigência de fiador — comum a todos os sites.

Estas funções trabalham em cima de texto puro (título/descrição já extraídos
da página) e não dependem de nenhuma estrutura de HTML específica de um site.
Cada scraper (idealista, imovirtual, ...) só precisa extrair um bloco de texto
razoável do anúncio e passar para `analisar_fiador`.
"""
from __future__ import annotations

import re

# Distância máxima (sem atravessar pontuação de fim de frase) tolerada entre
# um verbo de dispensa ("dispensa", "não exige"...) e a palavra "fiador",
# para casar frases como "o senhorio dispensa a apresentação de fiador" sem
# também casar um "dispensa"/"não" de outro assunto qualquer, em outra frase
# da página, com um "fiador" mencionado bem mais adiante — era exatamente
# esse o bug do padrão antigo "dispensa.*fiador", sem nenhum limite.
_JANELA_PROXIMIDADE_FIADOR = r"[^.!?]{0,40}"

# "fiador" ou "fiadores" (plural, comum em anúncios do Imovirtual: "Fiadores
# Idóneos"). Nota: o "es" do plural é opcional como grupo inteiro — "fiador"
# + "s?" sozinho exigiria sempre o "e" (só casaria "fiadore"/"fiadores").
_FIADOR = r"fiador(?:es)?"

PADROES_EXPLICITOS = [
    rf"\bsem {_FIADOR}\b",
    rf"\bsem necessidade de {_FIADOR}\b",
    rf"\bsem exig[êe]ncia de {_FIADOR}\b",
    # cobre "não exijo/exija" (1ª pessoa, forma irregular) e "não
    # exige/exigem/exigia/exigimos" (demais conjugações de "exigir") antes
    # de "fiador", com filler limitado à mesma frase.
    rf"\bn[ãa]o\s+exi[jg]\w*{_JANELA_PROXIMIDADE_FIADOR}\b{_FIADOR}\b",
    # forma pós-posta: "fiador não é necessário/obrigatório"
    rf"\b{_FIADOR}\b{_JANELA_PROXIMIDADE_FIADOR}\bn[ãa]o\s+(?:é|e|era)\s+(?:necess[áa]ri[oa]|obrigat[óo]ri[oa])\b",
    rf"\bisent[oa]\s+de\s+{_FIADOR}\b",
    # "na ausência de fiador[es] (terá de ser analisado/aceite/...)" — o
    # senhorio prevê o caso de não haver fiador e trata como situação a
    # avaliar, não como impeditivo. Regressão: um anúncio real ("Na ausência
    # de Fiador terá de ser analisado 4 rendas...") caía em EXIGE FIADOR
    # porque nenhum padrão cobria essa construção.
    rf"\bna\s+aus[êe]ncia\s+d[eo]\s+{_FIADOR}\b",
    # mesma ideia da "ausência de fiador", mas na forma condicional "caso/se
    # não tenha fiador". Regressão: anúncio real ("Nos casos em que não
    # tenha fiador, poderemos analisar os comprovativos do Inquilino e
    # reavaliar as condições.") caía em EXIGE FIADOR.
    rf"\bn[ãa]o\s+(?:tenha|tiver|tenham|tiverem|tem|t[êe]m|tinha)\s+{_FIADOR}\b",
    # "não pedimos/exigimos/solicitamos ... nem fiador" — a negação inicial
    # (não + verbo) se estende ao fiador via "nem". Regressão: anúncio real
    # ("Não pedimos caução nem fiador, somente os quatro meses de
    # entrada...") caía em EXIGE FIADOR porque só "sem fiador" era coberto,
    # não "não ... nem fiador".
    rf"\bn[ãa]o\b{_JANELA_PROXIMIDADE_FIADOR}\bnem\s+{_FIADOR}\b",
    # janela curta (não a frase toda) entre "fiador" e "opcional/dispensável":
    # cobre "fiador dispensável" (colado, forma original) e "fiador poderá/
    # pode ser dispensável" (com o verbo pelo meio), mas não uma frase mais
    # longa onde "dispensável" na verdade qualifica outra coisa (ex.: "fiador
    # obrigatório, mas o depósito é dispensável"). Regressão: anúncio real
    # ("Fiador poderá ser dispensável após análise da proposta") caía em
    # EXIGE FIADOR porque o padrão antigo exigia adjacência total.
    rf"\b{_FIADOR}\s+(?:pod(?:e|er[áa])\s+ser\s+)?(?:opcional|dispens[áa]vel)\b",
    rf"\bdispens\w*{_JANELA_PROXIMIDADE_FIADOR}\b{_FIADOR}\b",
    r"\bsubstitu[íi]vel por cau[çc][ãa]o\b",
    r"\bcau[çc][ãa]o refor[çc]ada\b",
    r"\brefor[çc]o de cau[çc][ãa]o\b",
    # "fiador ou caução" — apresenta as duas opções lado a lado, ou seja,
    # fiador é substituível por caução. Regressão: anúncio real ("Fiador ou
    # caução no valor equivalente a 3 meses de renda.") caía em EXIGE
    # FIADOR.
    rf"\b{_FIADOR}\s+ou\s+cau[çc][ãa]o\b",
    # "fiador se necessário" — condiciona a exigência a uma análise, não é
    # uma exigência incondicional. Adjacência exigida (sem janela) porque
    # "se necessário" solto em outro ponto da frase costuma qualificar outra
    # coisa (ex.: documentos extra), não o fiador em si.
    rf"\b{_FIADOR}\s+se\s+necess[áa]rio\b",
    # "poderá/pode ser solicitado/pedido/exigido fiador" — pedido
    # condicionado a uma análise prévia, não uma exigência de partida.
    rf"\bpod(?:e|er[áa])\s+ser\s+(?:solicitad|pedid|exigid)[oa]\s+{_FIADOR}\b",
]


def limpar_texto_cookie_banner(texto: str) -> str:
    if not texto:
        return texto

    texto = re.sub(r"No idealista utilizamos cookies.*?política de cookies\.?", " ", texto, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r"Nós e os nossos fornecedores efetuamos o seguinte tratamento de dados:.*?\.", " ", texto, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def extrair_bloco_do_anuncio(texto: str) -> str:
    """Corta o texto a partir do primeiro marcador de descrição conhecido.

    Sites cuja descrição já vem limpa (ex.: Imovirtual, via JSON-LD) não têm
    nenhum desses marcadores — a função devolve o texto original sem alterar
    nada, então é seguro chamá-la sempre, independente da origem do texto.
    """
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

    É um fallback: quando o site já expõe a tipologia de forma estruturada
    (ex.: Imovirtual, via JSON-LD), use aquele valor diretamente em vez desta
    função. Não há fallback de "primeiro número solto no texto" — chegou a
    existir um, mas causava falsos positivos (ex.: o "60" do número da rua,
    ou "2" de "a 2 minutos da estação", virando "T60"/"T2" por engano). Sem
    um "Txx" explícito perto de uma palavra do tipo de imóvel, o resultado
    fica como "Indefinida" — mais seguro do que adivinhar.
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

    É um fallback: quando o site expõe esse dado de forma estruturada (ex.:
    Imovirtual, via JSON-LD; idealista, via elemento ".professional-name"),
    prefira aquela fonte — bem mais confiável do que procurar as palavras
    "particular"/"profissional" soltas no texto, que podem aparecer em
    frases sem relação nenhuma com o tipo de anunciante (ex.: "estacionamento
    particular", "acabamento profissional").
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

    match = re.search(_FIADOR, texto_normalizado, re.IGNORECASE)
    if not match:
        return None
    inicio = max(0, match.start() - 90)
    fim = min(len(texto_normalizado), match.end() + 220)
    return texto_normalizado[inicio:fim].strip()


TAMANHO_DESCRICAO_TRUNCADA_ANTIGA = 253


def descricao_parece_truncada(descricao: str) -> bool:
    """Detecta a descrição truncada em ~250 caracteres do formato antigo.

    Anúncios coletados antes da descrição completa ser guardada (ver
    `scraper.py`) ficaram com só um recorte de 250 caracteres + reticências
    salvo permanentemente. A assinatura é bem específica — tamanho exato e
    termina em "..." — pra não confundir com uma descrição de verdade que só
    termine com reticências por coincidência.
    """
    if not descricao:
        return False
    return len(descricao) == TAMANHO_DESCRICAO_TRUNCADA_ANTIGA and descricao.endswith("...")


def detectar_bloqueio(texto: str) -> bool:
    """Detecta se a página caiu numa proteção anti-bot (Cloudflare, captcha, etc.)."""
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


def detectar_anuncio_indisponivel(texto: str) -> bool:
    """Detecta se a página indica que o anúncio já não está disponível.

    Cobre as mensagens típicas de "arrendado"/"removido pelo anunciante" do
    idealista e do Imovirtual, além de páginas de erro genéricas para as
    quais um anúncio removido costuma redirecionar. O texto exato varia
    entre sites e pode mudar com o tempo, então os padrões abaixo exigem
    frases razoavelmente específicas: um falso negativo só adia a marcação
    para a próxima verificação, mas um falso positivo esconderia por engano
    um anúncio que ainda está ativo.
    """
    if not texto or not texto.strip():
        return False

    texto_lower = " ".join(texto.split()).lower()
    padroes_indisponivel = [
        r"an[uú]ncio\s+j[áa]\s+n[ãa]o\s+est[áa]\s+dispon[íi]vel",
        r"im[óo]vel\s+j[áa]\s+n[ãa]o\s+est[áa]\s+dispon[íi]vel",
        r"an[uú]ncio\s+(?:foi\s+)?removido",
        r"an[uú]ncio\s+(?:j[áa]\s+)?expirad[oa]",
        r"an[uú]ncio\s+inativo",
        r"oferta\s+j[áa]\s+n[ãa]o\s+(?:est[áa]|se\s+encontra)\s+dispon[íi]vel",
        r"esta\s+p[áa]gina\s+n[ãa]o\s+existe",
        r"p[áa]gina\s+n[ãa]o\s+encontrada",
    ]
    return any(re.search(padrao, texto_lower) for padrao in padroes_indisponivel)


def analisar_fiador(texto: str) -> tuple[bool, str, str | None]:
    if not texto or not texto.strip():
        return False, "ERRO_TEXTO_VAZIO", None

    texto = extrair_bloco_do_anuncio(texto)
    if not texto.strip():
        return False, "ERRO_TEXTO_VAZIO", None

    if detectar_bloqueio(texto):
        trecho = extrair_trecho_status(texto, r"demasiados pedidos|aguarde uns momentos|ray id|cloudflare|captcha|too many requests")
        return False, "BLOQUEADO_POR_ANTI_BOT", trecho or texto[:300]

    # 1. Verifica se há confirmação explícita de flexibilidade
    for padrao in PADROES_EXPLICITOS:
        trecho = extrair_trecho_status(texto, padrao)
        if trecho:
            return True, "CONFIRMADO (Explícito/Flexível)", trecho

    # 2. Verifica ausência TOTAL da palavra fiador
    if not re.search(_FIADOR, texto, re.IGNORECASE):
        return True, "SEM MENÇÃO (Não cita fiador)", None

    trecho = extrair_trecho_status(texto)
    return True, "EXIGE FIADOR", trecho
