"""Reclassifica anúncios já guardados com a lógica atual de `analisar_fiador`.

Útil sempre que os padrões de `classificacao.py` mudam (ex.: corrigindo um
falso positivo/negativo descoberto depois): como a descrição completa de
cada anúncio já fica salva (ver `scraper.py`/`scraper_imovirtual.py`), dá
pra reaplicar a classificação sobre o que já está em disco, sem reabrir
nenhuma página nem esperar uma nova varredura.

Roda com `python scripts/reclassificar.py` a partir da raiz do projeto.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from classificacao import analisar_fiador
from storage import FONTES, Storage, default_storage

# Únicos status que significam "a palavra fiador foi mesmo encontrada no
# texto". Usado pela proteção contra descrição truncada (ver
# `_pode_confiar_na_reclassificacao`).
_STATUS_QUE_CONFIRMAM_MENCAO_DE_FIADOR = {"EXIGE FIADOR", "CONFIRMADO (Explícito/Flexível)"}


def _pode_confiar_na_reclassificacao(item: dict, novo_status: str) -> bool:
    """Evita regressão em anúncios com a descrição antiga truncada em 250 caracteres.

    Alguns anúncios foram salvos antes da descrição completa ser guardada
    (ver README) — na época, a classificação rodou sobre o texto completo da
    página e só *depois* a descrição foi truncada para armazenamento, então
    o status salvo pode ser correto mesmo sem "fiador" aparecer no texto que
    sobrou. Reclassificar esse texto truncado, sem essa proteção, rebaixaria
    esses anúncios pra "SEM MENÇÃO" por falta de texto, não porque a
    classificação estivesse errada — foi exatamente isso que aconteceu na
    primeira vez que este script rodou contra dados reais.
    """
    if novo_status != "SEM MENÇÃO (Não cita fiador)":
        return True
    if item.get("status") not in _STATUS_QUE_CONFIRMAM_MENCAO_DE_FIADOR:
        return True
    return "fiador" in (item.get("descricao") or "").lower()


def reclassificar_fonte(fonte: str, store: Storage | None = None) -> int:
    """Reaplica `analisar_fiador` a todos os anúncios guardados de `fonte`.

    Devolve quantos anúncios tiveram o status alterado. Pula (sem contar)
    anúncios cuja reclassificação não seria confiável — ver
    `_pode_confiar_na_reclassificacao`.
    """
    store = store or default_storage
    resultados = store.carregar_resultados(fonte)
    alterados = 0

    for item in resultados:
        passou_filtro, status, trecho = analisar_fiador(item.get("descricao", ""))
        if not _pode_confiar_na_reclassificacao(item, status):
            continue
        if item.get("status") != status:
            alterados += 1
        item["status"] = status
        item["trecho_status"] = trecho
        item["passou_filtro"] = passou_filtro

    if alterados:
        store.guardar_resultados(fonte, resultados)
    return alterados


def reclassificar_todas(store: Storage | None = None) -> dict[str, int]:
    """Reclassifica todas as fontes registadas. Devolve alterados por fonte."""
    store = store or default_storage
    return {fonte: reclassificar_fonte(fonte, store) for fonte in FONTES}


if __name__ == "__main__":
    alterados_por_fonte = reclassificar_todas()
    for fonte, alterados in alterados_por_fonte.items():
        print(f"{fonte}: {alterados} anúncio(s) com status alterado")
    print(f"Total: {sum(alterados_por_fonte.values())}")
