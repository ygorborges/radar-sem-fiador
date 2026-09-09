"""Divisão administrativa de Portugal (concelho ⊃ freguesia), para corrigir e
uniformizar a localização extraída dos anúncios.

Os scrapers já extraem a freguesia de forma relativamente confiável (nome
oficial, só formatado de um jeito diferente por cada site), mas o "concelho"
que cada site expõe é inconsistente:

- O Imovirtual publica o *distrito* no campo que parecia ser o concelho
  (`address.addressRegion` do schema.org é "Porto" — o distrito, que cobre
  Porto, Gondomar, Maia, Matosinhos, Valongo, Vila Nova de Gaia e mais 12
  concelhos — não o concelho "Porto" especificamente).
- O idealista, quando o anúncio não é da cidade do Porto, às vezes junta
  concelho e distrito numa única string no último nível da hierarquia de
  localização (ex.: "Vila Nova de Gaia, Porto").

Em vez de confiar nesse campo, `concelho_da_freguesia` deriva o concelho
correto a partir da freguesia, usando a divisão administrativa oficial
pós-reorganização de 2013 (`concelhos_freguesias.json`: 306 concelhos, 3092
freguesias — bate com o total oficial do país). Gerado a partir de
https://gist.github.com/tomahock/a6c07dd255d04499d8336237e35a4827
(distritos-concelhos-freguesias-Portugal.json, actualizado 2016-07-12),
removendo o nível de distrito (não usado por este projeto) e o prefixo
"União das freguesias de" de cada nome.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

_ARQUIVO = Path(__file__).resolve().parent / "concelhos_freguesias.json"

with _ARQUIVO.open("r", encoding="utf-8") as _f:
    CONCELHOS_FREGUESIAS: dict[str, list[str]] = json.load(_f)


def _normalizar(texto: str) -> str:
    """minúsculas, sem acentos, espaços colapsados — só para comparação."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def _componentes(nome_freguesia: str) -> frozenset[str]:
    """Quebra o nome de uma freguesia (união ou não) nas paróquias que a compõem.

    Cada site formata uniões de freguesias de um jeito diferente — o
    idealista separa tudo com " - " ("Cedofeita - Santo Ildefonso - Sé -
    Miragaia - São Nicolau - Vitória"), o nome oficial usa vírgulas e um "e"
    antes do último ("Cedofeita, Santo Ildefonso, Sé, Miragaia, São Nicolau e
    Vitória"). Comparar como *conjunto* de componentes normalizados (em vez
    da string inteira) resolve essa diferença de formatação de uma vez,
    sem depender de acertar a pontuação exata de cada site.
    """
    texto_com_virgulas = re.sub(r"\s*-\s*", ", ", nome_freguesia)
    partes = re.split(r",| e ", texto_com_virgulas)
    return frozenset(_normalizar(p) for p in partes if p.strip())


def _construir_indices():
    conjunto_para_concelhos: dict[frozenset[str], set[str]] = {}
    componente_para_concelhos: dict[str, set[str]] = {}

    for concelho, freguesias in CONCELHOS_FREGUESIAS.items():
        for freguesia in freguesias:
            componentes = _componentes(freguesia)
            conjunto_para_concelhos.setdefault(componentes, set()).add(concelho)
            for componente in componentes:
                componente_para_concelhos.setdefault(componente, set()).add(concelho)

    return conjunto_para_concelhos, componente_para_concelhos


_CONJUNTO_PARA_CONCELHOS, _COMPONENTE_PARA_CONCELHOS = _construir_indices()


def _resolver(candidatos: set[str], dica_cidade: Optional[str]) -> Optional[str]:
    """Escolhe um concelho entre `candidatos`, usando `dica_cidade` para desempatar.

    Nomes de freguesia se repetem por Portugal inteiro mais do que se
    esperaria — "Paranhos" existe no Porto e em Seia; "Oliveira do Douro"
    existe em Vila Nova de Gaia e em Cinfães. Sem pista nenhuma, mais de um
    candidato significa "não sei" (devolve `None`). Com uma pista (o texto
    bruto da fonte, que às vezes inclui o nome do concelho mesmo grudado a
    outra coisa — ex.: "Vila Nova de Gaia, Porto" — mesmo sem servir como
    concelho por si só), o candidato cujo nome aparece nela desempata, desde
    que seja o único a aparecer.
    """
    if len(candidatos) == 1:
        return next(iter(candidatos))

    if len(candidatos) > 1 and dica_cidade:
        dica_normalizada = _normalizar(dica_cidade)
        acertos = [c for c in candidatos if _normalizar(c) in dica_normalizada]
        if len(acertos) == 1:
            return acertos[0]

    return None


def concelho_da_freguesia(texto_freguesia: str, dica_cidade: Optional[str] = None) -> Optional[str]:
    """Devolve o concelho oficial a que `texto_freguesia` pertence, ou `None`.

    Para um nome composto (união, 2+ componentes) tenta primeiro a
    correspondência do conjunto inteiro — bate com a união completa em
    qualquer formatação/ordem, e a combinação já é específica o suficiente
    pra não coincidir com a de outro concelho por acaso. Um nome de um único
    componente pula direto pra correspondência por componente (mesmo índice
    usado no fallback abaixo), porque nomes curtos e comuns se repetem em
    concelhos bem diferentes pelo país; tratar esse caso como o mesmo
    problema de ambiguidade do fallback, em vez de uma correspondência
    "exata" supostamente mais confiável, evita atribuir esses nomes ao
    concelho errado. Ver `_resolver` sobre o papel de `dica_cidade`.
    """
    if not texto_freguesia or not texto_freguesia.strip():
        return None

    componentes = _componentes(texto_freguesia)

    if len(componentes) > 1:
        resolvido = _resolver(_CONJUNTO_PARA_CONCELHOS.get(componentes, set()), dica_cidade)
        if resolvido:
            return resolvido

    for componente in componentes:
        resolvido = _resolver(_COMPONENTE_PARA_CONCELHOS.get(componente, set()), dica_cidade)
        if resolvido:
            return resolvido

    return None


def canonicalizar_freguesia(texto_freguesia: str) -> str:
    """Devolve o nome oficial da freguesia correspondente a `texto_freguesia`.

    Uniformiza a formatação entre fontes (idealista vs. Imovirtual) para que
    a mesma freguesia real não apareça duas vezes no filtro só por causa da
    pontuação — inclusive quando um site abrevia um componente do nome (ex.:
    o Imovirtual às vezes encurta "Santo Ildefonso" para só "Ildefonso").
    Por isso a escolha usa a freguesia do concelho com mais componentes em
    comum com o texto de entrada, em vez de exigir correspondência exata. Se
    não reconhecer nenhuma freguesia, devolve o texto original sem alterar.
    """
    concelho = concelho_da_freguesia(texto_freguesia)
    if not concelho:
        return texto_freguesia

    componentes_procurados = _componentes(texto_freguesia)
    melhor_nome = texto_freguesia
    melhor_pontuacao = 0
    for freguesia in CONCELHOS_FREGUESIAS[concelho]:
        pontuacao = len(_componentes(freguesia) & componentes_procurados)
        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_nome = freguesia

    return melhor_nome
