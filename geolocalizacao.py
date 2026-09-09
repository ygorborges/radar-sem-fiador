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
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Optional

from storage import Storage

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "RadarArrendamento/1.0 (+https://github.com/ygorborges/radar-sem-fiador)"
INTERVALO_MINIMO_SEGUNDOS = 1.0

_ultimo_pedido = 0.0


def _respeitar_limite_de_taxa() -> None:
    global _ultimo_pedido
    decorrido = time.monotonic() - _ultimo_pedido
    if decorrido < INTERVALO_MINIMO_SEGUNDOS:
        time.sleep(INTERVALO_MINIMO_SEGUNDOS - decorrido)
    _ultimo_pedido = time.monotonic()


def geocodificar(endereco: str) -> Optional[tuple[float, float]]:
    """Consulta o Nominatim; devolve `(lat, lon)` ou `None` se não achar/falhar."""
    if not endereco or not endereco.strip():
        return None

    query = urllib.parse.urlencode({"q": endereco, "format": "json", "limit": 1})
    request = urllib.request.Request(
        f"{NOMINATIM_URL}?{query}",
        headers={"User-Agent": USER_AGENT},
    )

    _respeitar_limite_de_taxa()
    try:
        with urllib.request.urlopen(request, timeout=10) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except Exception:
        return None

    if not dados:
        return None
    try:
        return float(dados[0]["lat"]), float(dados[0]["lon"])
    except (KeyError, ValueError, TypeError, IndexError):
        return None


def geocodificar_com_cache(endereco: str, store: Storage) -> Optional[tuple[float, float]]:
    """Como `geocodificar`, mas reaproveita (e alimenta) o cache em disco.

    Um resultado "não encontrado" também é cacheado (como `None`), para não
    tentar geocodificar de novo, a cada execução, um endereço que a Nominatim
    já não conseguiu resolver antes.
    """
    if not endereco or not endereco.strip():
        return None

    cache = store.carregar_cache_geocodificacao()
    if endereco in cache:
        valor = cache[endereco]
        return (valor[0], valor[1]) if valor else None

    resultado = geocodificar(endereco)
    cache[endereco] = list(resultado) if resultado else None
    store.guardar_cache_geocodificacao(cache)
    return resultado
