"""Corrige o concelho (e uniformiza a freguesia) dos anúncios já guardados.

Os concelhos extraídos antes do módulo `divisoes_administrativas` existir
vinham direto do texto de cada site: o campo `addressRegion` do Imovirtual
(na verdade o *distrito*, não o concelho) ou o último nível da lista de
localização do idealista (que às vezes junta concelho e distrito numa única
string, tipo "Vila Nova de Gaia, Porto"). Este script reprocessa o que já
está em `data/` usando a divisão administrativa oficial — a freguesia já
guardada é o suficiente, não precisa reabrir nenhuma página.
"""
from __future__ import annotations

import divisoes_administrativas
from storage import FONTES, Storage, default_storage


def corrigir_fonte(fonte: str, store: Storage | None = None) -> int:
    """Corrige concelho/freguesia de todos os anúncios guardados de `fonte`.

    Devolve quantos anúncios tiveram a localização alterada. Anúncios sem
    `localizacao` (ou sem freguesia guardada) são ignorados — não há nada a
    corrigir sem uma freguesia para consultar. Quando a freguesia guardada
    não é reconhecida com confiança (nome ambíguo entre concelhos, ou zona
    informal sem correspondência oficial), o concelho é limpo (`None`) em
    vez de mantido — um valor antigo não confiável (às vezes nem um nome de
    concelho de verdade) é pior do que não ter nenhum.
    """
    store = store or default_storage
    resultados = store.carregar_resultados(fonte)
    alterados = 0

    for item in resultados:
        localizacao = item.get("localizacao")
        if not localizacao or not localizacao.get("freguesia"):
            continue

        freguesia_atual = localizacao["freguesia"]
        # O concelho antigo (possivelmente errado) ainda serve como pista de
        # desempate quando a freguesia é ambígua: pro idealista, ele *era*
        # literalmente o último item bruto da lista de localização (ex.:
        # "Vila Nova de Gaia, Porto") — mesmo capenga, costuma conter o nome
        # certo. Pro Imovirtual é só o distrito ("Porto"), que não desempata
        # nada sozinho, mas também não atrapalha.
        concelho_correto = divisoes_administrativas.concelho_da_freguesia(
            freguesia_atual, dica_cidade=localizacao.get("concelho")
        )
        if not concelho_correto:
            # Freguesia ambígua ou não reconhecida (ex.: "Paranhos" sozinho,
            # que existe tanto no Porto quanto em Seia) — mais vale limpar um
            # concelho antigo não confiável do que deixar um valor errado
            # (às vezes nem um concelho de verdade, ex.: "Vila Nova de Gaia,
            # Porto") persistir só porque não conseguimos confirmar um novo.
            if localizacao.get("concelho") is not None:
                localizacao["concelho"] = None
                alterados += 1
            continue

        freguesia_canonica = divisoes_administrativas.canonicalizar_freguesia(freguesia_atual)
        if localizacao.get("concelho") == concelho_correto and freguesia_atual == freguesia_canonica:
            continue

        localizacao["concelho"] = concelho_correto
        localizacao["freguesia"] = freguesia_canonica
        alterados += 1

    if alterados:
        store.guardar_resultados(fonte, resultados)
    return alterados


def corrigir_todas(store: Storage | None = None) -> dict[str, int]:
    """Corrige todas as fontes registadas. Devolve alterados por fonte."""
    store = store or default_storage
    return {fonte: corrigir_fonte(fonte, store) for fonte in FONTES}


if __name__ == "__main__":
    alterados_por_fonte = corrigir_todas()
    for fonte, alterados in alterados_por_fonte.items():
        print(f"{fonte}: {alterados} anúncio(s) com localização corrigida")
    print(f"Total: {sum(alterados_por_fonte.values())}")
