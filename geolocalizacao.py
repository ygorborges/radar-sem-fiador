"""Geocodificação de endereços/zonas para o mapa de anúncios.

Só o idealista precisa disto: a página não expõe a coordenada exata (o
`mapConfig.latitude`/`longitude` embutido no HTML vem sempre vazio), só uma
lista textual de localização (rua, bairro, zona, cidade — ver
`scraper.extrair_localizacao_pagina`). O Imovirtual já publica a coordenada
pronta no JSON-LD, então não passa por aqui (ver
`scraper_imovirtual.extrair_localizacao_pagina`).

Usa a API pública do Nominatim (OpenStreetMap), respeitando a política de uso
dela: no máximo 1 pedido por segundo e um User-Agent identificável — nunca o
padrão genérico do urllib, que a própria Nominatim rejeita. Os resultados são
cacheados em `data/geocode_cache.json` (via `Storage`) porque muitos anúncios
do idealista compartilham a mesma rua ou o mesmo bairro; sem cache, cada
verificação/varredura repetiria pedidos idênticos à toa.

Quando se conhece a cidade (concelho já confirmado via
`divisoes_administrativas`), usa busca com verificação de cidade em vez de
confiar cegamente no primeiro resultado — dois achados reais mostraram que
nem a busca estruturada nem a livre, sozinhas, bastam:

1. Pra um endereço de rua de verdade, a busca **estruturada** (`street`/
   `city` separados) normalmente ajuda... mas pra "Praça da República" —
   nome de rua/praça comum, repetido em dezenas de cidades — a Nominatim
   devolvia, em primeiro lugar, uma "Praça da República" na Póvoa de
   Varzim, mesmo pedindo `city=Porto`. O parâmetro `city` da Nominatim não
   filtra com rigor; ele também compara com o campo `county` (que aqui é o
   *distrito* do Porto, cobrindo Póvoa de Varzim, Paços de Ferreira,
   Amarante e mais uma dúzia de concelhos), e o resultado errado tinha uma
   pontuação de "importância" (popularidade do local no OSM, não
   relevância geográfica) maior que o certo.
2. Pra uma freguesia (nome de área administrativa, não de rua — usado
   quando não há endereço de rua confiável), a mesma busca estruturada
   simplesmente não encontra nada: o campo `street` da Nominatim não
   reconhece um valor com vírgulas ("Cedofeita, Santo Ildefonso, Sé,
   Miragaia, São Nicolau e Vitória") como nome de rua. A busca **livre**
   (`q=`) com o nome completo funciona bem pra esse caso.

A correção comum aos dois casos (`_consultar_nominatim`): pedir vários
candidatos (`NUM_CANDIDATOS_POR_CONSULTA`) e escolher, entre eles, o
primeiro cujo `address.city`/`town`/`village`/`municipality` bate
exatamente com a cidade pedida — ignora a ordem de "importância" da
Nominatim, que não é confiável pra esse propósito. `geocodificar` escolhe
entre busca estruturada (endereço de rua) e livre (freguesia/área) pelo
parâmetro `estruturado`.
"""
from __future__ import annotations

import json
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Optional

from storage import Storage

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "RadarArrendamento/1.0 (+https://github.com/ygorborges/radar-sem-fiador)"
INTERVALO_MINIMO_SEGUNDOS = 1.0
NUM_CANDIDATOS_POR_CONSULTA = 8

_ultimo_pedido = 0.0


def _respeitar_limite_de_taxa() -> None:
    global _ultimo_pedido
    decorrido = time.monotonic() - _ultimo_pedido
    if decorrido < INTERVALO_MINIMO_SEGUNDOS:
        time.sleep(INTERVALO_MINIMO_SEGUNDOS - decorrido)
    _ultimo_pedido = time.monotonic()


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().lower()


def _consultar_nominatim(params: dict, *, cidade_esperada: Optional[str] = None) -> Optional[tuple[float, float]]:
    limite = NUM_CANDIDATOS_POR_CONSULTA if cidade_esperada else 1
    query = urllib.parse.urlencode({**params, "format": "json", "limit": limite, "addressdetails": 1})
    request = urllib.request.Request(
        f"{NOMINATIM_URL}?{query}",
        headers={"User-Agent": USER_AGENT},
    )

    _respeitar_limite_de_taxa()
    try:
        with urllib.request.urlopen(request, timeout=10) as resposta:
            candidatos = json.loads(resposta.read().decode("utf-8"))
    except Exception:
        return None

    if not candidatos:
        return None

    if cidade_esperada:
        cidade_normalizada = _normalizar(cidade_esperada)
        for candidato in candidatos:
            endereco = candidato.get("address") or {}
            campos_cidade = (endereco.get("city"), endereco.get("town"), endereco.get("village"), endereco.get("municipality"))
            if any(campo and _normalizar(campo) == cidade_normalizada for campo in campos_cidade):
                try:
                    return float(candidato["lat"]), float(candidato["lon"])
                except (KeyError, ValueError, TypeError):
                    continue
        # Nenhum candidato confirma a cidade certa nos detalhes de endereço —
        # mais vale não geocodificar do que devolver um lugar comprovadamente
        # errado (ex.: a "Praça da República" da Póvoa de Varzim).
        return None

    try:
        return float(candidatos[0]["lat"]), float(candidatos[0]["lon"])
    except (KeyError, ValueError, TypeError, IndexError):
        return None


def geocodificar(
    endereco: str, cidade: Optional[str] = None, estruturado: bool = True
) -> Optional[tuple[float, float]]:
    """Consulta o Nominatim; devolve `(lat, lon)` ou `None` se não achar/falhar.

    Com `cidade` informada, sempre verifica que o candidato escolhido
    confirma essa cidade nos detalhes de endereço (ver docstring do módulo —
    nem `city=` estruturado nem `q=` livre bastam sozinhos). `estruturado`
    escolhe a forma da consulta: `True` (padrão) usa `street=endereco,
    city=cidade` — para um endereço de rua de verdade; `False` usa busca
    livre `q="endereco, cidade, Portugal"` — para nome de freguesia/área,
    que a busca estruturada não reconhece como "rua". Sem `cidade`, cai
    para a busca livre de sempre (`q=endereco`), sem essa verificação.
    """
    if not endereco or not endereco.strip():
        return None

    if cidade and estruturado:
        params = {"street": endereco, "city": cidade, "country": "Portugal"}
        return _consultar_nominatim(params, cidade_esperada=cidade)

    if cidade:
        return _consultar_nominatim({"q": f"{endereco}, {cidade}, Portugal"}, cidade_esperada=cidade)

    return _consultar_nominatim({"q": endereco})


def geocodificar_com_cache(
    endereco: str, store: Storage, cidade: Optional[str] = None, estruturado: bool = True
) -> Optional[tuple[float, float]]:
    """Como `geocodificar`, mas reaproveita (e alimenta) o cache em disco.

    A chave do cache inclui a cidade e o modo de busca quando informados —
    busca estruturada e livre pro mesmo texto+cidade são consultas
    diferentes, então precisam de entradas de cache separadas. Um resultado
    "não encontrado" também é cacheado (como `None`), para não tentar
    geocodificar de novo, a cada execução, algo que a Nominatim já não
    conseguiu resolver antes.
    """
    if not endereco or not endereco.strip():
        return None

    if cidade:
        chave_cache = f"{endereco}, {cidade}" if estruturado else f"{endereco}, {cidade} (livre)"
    else:
        chave_cache = endereco

    cache = store.carregar_cache_geocodificacao()
    if chave_cache in cache:
        valor = cache[chave_cache]
        return (valor[0], valor[1]) if valor else None

    resultado = geocodificar(endereco, cidade=cidade, estruturado=estruturado)
    cache[chave_cache] = list(resultado) if resultado else None
    store.guardar_cache_geocodificacao(cache)
    return resultado
