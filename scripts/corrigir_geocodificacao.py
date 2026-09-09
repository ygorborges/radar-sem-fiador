"""Re-geocodifica os anúncios do idealista com verificação de cidade.

A geocodificação antiga usava uma única string livre ("rua, cidade,
Portugal") sem verificar o resultado — nomes de rua comuns em Portugal
("Praça da República", "Rua Direita"...) existem em dezenas de cidades, e a
Nominatim às vezes resolvia pra cidade errada mesmo com "Porto" dentro da
própria string. `geolocalizacao.geocodificar` (com `cidade=`) agora só
aceita um candidato cujo endereço confirme a cidade certa; quando o
endereço de rua não confirma nada, este script cai para geocodificar a
freguesia (nível já confiável, ver `divisoes_administrativas`).

Só o idealista geocodifica (o Imovirtual usa coordenadas prontas do próprio
site) — reaproveita o concelho já corrigido
(`divisoes_administrativas`/`corrigir_concelhos.py`) como a cidade da busca.
Bate direto na Nominatim (respeitando o limite de 1 pedido por segundo),
sem precisar reabrir nenhuma página.

Roda com `python scripts/corrigir_geocodificacao.py` a partir da raiz do projeto.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geolocalizacao
from storage import Storage, default_storage

FONTE = "idealista"


def corrigir_fonte(fonte: str = FONTE, store: Storage | None = None) -> int:
    """Re-geocodifica todos os anúncios de `fonte` com concelho confirmado.

    Devolve quantos anúncios tiveram a coordenada (ou a precisão) alterada.
    Anúncios sem `localizacao` ou sem concelho confirmado são ignorados —
    sem um concelho, não há como montar uma busca estruturada melhor do que
    a que já foi feita. Quando o endereço de rua não confirma a cidade certa
    (`geocodificar_com_cache` devolve `None` — ver `geolocalizacao.py`),
    cai para geocodificar a freguesia em vez da rua, marcando o anúncio como
    aproximado: manter a coordenada antiga (que também não foi confirmada
    contra a cidade certa, no formato antigo) seria arriscar continuar
    errado só por preservar a aparência de precisão.
    """
    store = store or default_storage
    resultados = store.carregar_resultados(fonte)
    alterados = 0

    for item in resultados:
        localizacao = item.get("localizacao")
        if not localizacao or not localizacao.get("concelho"):
            continue

        concelho = localizacao["concelho"]
        preciso_novo = bool(localizacao.get("preciso"))
        coords = None

        if preciso_novo and localizacao.get("texto"):
            coords = geolocalizacao.geocodificar_com_cache(localizacao["texto"], store, cidade=concelho)

        if not coords and localizacao.get("freguesia"):
            # Busca livre, não estruturada: o campo `street=` da Nominatim
            # não reconhece um nome de freguesia com vírgulas como rua (achado
            # real — devolvia zero resultados pra "Cedofeita, Santo
            # Ildefonso, Sé, Miragaia, São Nicolau e Vitória").
            coords = geolocalizacao.geocodificar_com_cache(
                localizacao["freguesia"], store, cidade=concelho, estruturado=False
            )
            preciso_novo = False

        if not coords:
            continue

        mudou_coords = (localizacao.get("lat"), localizacao.get("lon")) != coords
        mudou_precisao = localizacao.get("preciso") != preciso_novo
        if mudou_coords or mudou_precisao:
            localizacao["lat"], localizacao["lon"] = coords
            localizacao["preciso"] = preciso_novo
            alterados += 1

    if alterados:
        store.guardar_resultados(fonte, resultados)
    return alterados


if __name__ == "__main__":
    alterados = corrigir_fonte()
    print(f"{FONTE}: {alterados} anúncio(s) com coordenadas corrigidas")
