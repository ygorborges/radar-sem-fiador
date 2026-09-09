"""Persistência em JSON usada pelos scrapers e pela API web.

Centraliza toda a leitura/escrita de ficheiros em `data/` (histórico,
resultados, configuração da URL de busca e favoritos) para que tanto os
scrapers quanto a aplicação Flask usem a mesma fonte de verdade.

Suporta múltiplos sites de origem ("fontes"). O histórico de anúncios já
visitados é único e partilhado entre fontes (os links já são globalmente
únicos por incluírem o domínio); resultados e a URL de busca configurada
são guardados por fonte.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent

URL_BASE_DEFAULT_IDEALISTA = (
    "https://www.idealista.pt/areas/arrendar-casas/com-preco-max_999,tamanho-min_50,"
    "apartamentos,moradias-independentes,moradias-geminadas,moradias-em-banda,"
    "t0,t1,t2,t3,t4-t5,arrendamento-longa-duracao/"
    "?shape=%28%28_tdzFp%7Cxs%40goBglAaC%7BhFvz%40ceCbpBmEdyE%7Ci%40xPjzB%7DbAb%7C%40c%7BAlSkc%40vlDc_B%60%5D%29%29"
    "&ordem=precos-asc"
)
# Nome antigo, mantido por compatibilidade com quem já importava esta constante.
URL_BASE_DEFAULT = URL_BASE_DEFAULT_IDEALISTA

URL_BASE_DEFAULT_IMOVIRTUAL = (
    "https://www.imovirtual.com/pt/resultados/arrendar/apartamento/porto/porto"
    "?distanceRadius=5&limit=36&priceMax=1000&areaMin=60&by=DEFAULT&direction=DESC"
)

# Registo central das fontes suportadas. Adicionar um novo site de scraping
# (ex.: OLX) é, na parte de armazenamento, só acrescentar uma entrada aqui.
FONTES: dict[str, dict] = {
    "idealista": {
        "label": "idealista.pt",
        "dominio": "https://www.idealista.pt",
        "url_default": URL_BASE_DEFAULT_IDEALISTA,
        "resultados_filename": "resultados_idealista.json",
    },
    "imovirtual": {
        "label": "Imovirtual",
        "dominio": "https://www.imovirtual.com",
        "url_default": URL_BASE_DEFAULT_IMOVIRTUAL,
        "resultados_filename": "resultados_imovirtual.json",
    },
}


class Storage:
    """Acesso aos ficheiros JSON/log de uma pasta `data/` específica.

    Recebe o diretório de dados no construtor (em vez de usar um caminho
    fixo) para que os testes possam apontar para uma pasta temporária sem
    tocar nos dados reais do utilizador.
    """

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.historico_path = self.data_dir / "historico_anuncios.json"
        self.config_path = self.data_dir / "config.json"
        self.favoritos_path = self.data_dir / "favoritos.json"
        self.ocultos_path = self.data_dir / "ocultos.json"
        self.geocode_cache_path = self.data_dir / "geocode_cache.json"
        self.log_path = self.data_dir / "scraper_log.txt"
        self._lock = threading.Lock()

    def ensure_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    def _write_json(self, path: Path, data: Any) -> None:
        self.ensure_dir()
        with self._lock:
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _validar_fonte(self, fonte: str) -> None:
        if fonte not in FONTES:
            raise ValueError(f"Fonte desconhecida: {fonte!r} (esperado uma de {sorted(FONTES)})")

    # ---- Histórico de anúncios já visitados (partilhado entre fontes) ------

    def carregar_historico(self) -> set[str]:
        dados = self._read_json(self.historico_path, [])
        if isinstance(dados, list):
            return {str(item) for item in dados}
        return set()

    def guardar_historico(self, historico: set[str]) -> None:
        self._write_json(self.historico_path, sorted(historico))

    # ---- Resultados da última varredura, por fonte --------------------------

    def _resultados_path(self, fonte: str) -> Path:
        self._validar_fonte(fonte)
        return self.data_dir / FONTES[fonte]["resultados_filename"]

    def carregar_resultados(self, fonte: str) -> list[dict]:
        dados = self._read_json(self._resultados_path(fonte), [])
        return dados if isinstance(dados, list) else []

    def carregar_resultados_todas_fontes(self) -> list[dict]:
        """Resultados de todas as fontes combinados, cada item com a chave "fonte"."""
        todos: list[dict] = []
        for fonte in FONTES:
            for item in self.carregar_resultados(fonte):
                item = dict(item)
                item.setdefault("fonte", fonte)
                todos.append(item)
        return todos

    def guardar_resultados(self, fonte: str, resultados: list[dict]) -> None:
        self._write_json(self._resultados_path(fonte), resultados)

    def atualizar_resultados(self, fonte: str, novos: list[dict]) -> list[dict]:
        """Mescla `novos` aos resultados já guardados dessa fonte, por `link`.

        Cada execução do scraper só revisita anúncios que ainda não estão no
        histórico, então uma simples sobrescrita apagaria os achados de
        execuções anteriores. Aqui, anúncios repetidos são atualizados no
        lugar e os demais são preservados; novos anúncios são anexados.
        """
        existentes = self.carregar_resultados(fonte)
        indice = {item.get("link"): pos for pos, item in enumerate(existentes) if item.get("link")}

        for item in novos:
            link = item.get("link")
            if link and link in indice:
                existentes[indice[link]] = item
            else:
                existentes.append(item)
                if link:
                    indice[link] = len(existentes) - 1

        self.guardar_resultados(fonte, existentes)
        return existentes

    def remover_resultado(self, fonte: str, link: str) -> bool:
        """Remove definitivamente um anúncio que saiu do ar (arrendado/removido).

        Usado pela verificação periódica (`verificador_disponibilidade.py`).
        O histórico de links já visitados (`historico_anuncios.json`) não é
        afetado — continua garantindo que o scraper nunca revisite esse link
        — então não há necessidade de guardar mais nada sobre o anúncio.
        Também limpa favoritos/ocultos associados a ele, para essas listas
        não acumularem referências a anúncios que não existem mais. Devolve
        `False` sem fazer nada se o link não existir nos resultados da fonte.
        """
        resultados = self.carregar_resultados(fonte)
        restantes = [item for item in resultados if item.get("link") != link]
        if len(restantes) == len(resultados):
            return False
        self.guardar_resultados(fonte, restantes)

        favoritos = self.carregar_favoritos()
        if link in favoritos:
            favoritos.discard(link)
            self.guardar_favoritos(favoritos)

        ocultos = self.carregar_ocultos()
        if link in ocultos:
            ocultos.discard(link)
            self.guardar_ocultos(ocultos)

        return True

    def atualizar_localizacao(self, fonte: str, link: str, localizacao: dict) -> None:
        """Preenche a localização (`lat`/`lon`/`preciso`/`texto`) de um anúncio já guardado.

        Usado tanto pelos scrapers (assim que um anúncio novo é coletado)
        quanto pela verificação periódica de disponibilidade, que aproveita a
        própria visita à página para preencher a localização de anúncios
        coletados antes dessa funcionalidade existir (ou cuja geocodificação
        havia falhado antes). Não faz nada se o link não existir na fonte.
        """
        resultados = self.carregar_resultados(fonte)
        for item in resultados:
            if item.get("link") == link:
                item["localizacao"] = localizacao
                self.guardar_resultados(fonte, resultados)
                return

    # ---- Cache de geocodificação (partilhado entre fontes) --------------------

    def carregar_cache_geocodificacao(self) -> dict:
        dados = self._read_json(self.geocode_cache_path, {})
        return dados if isinstance(dados, dict) else {}

    def guardar_cache_geocodificacao(self, cache: dict) -> None:
        self._write_json(self.geocode_cache_path, cache)

    # ---- Configuração da URL de busca, por fonte -----------------------------

    def _ler_config_bruta(self) -> dict:
        dados = self._read_json(self.config_path, {})
        if not isinstance(dados, dict):
            return {}
        # Formato antigo (uma única fonte, sem aninhamento): {"url_atual": "..."}
        # é tratado como um override só da fonte "idealista".
        if "url_atual" in dados and not any(fonte in dados for fonte in FONTES):
            return {"idealista": {"url_atual": dados.get("url_atual")}}
        return dados

    def carregar_config(self) -> dict[str, dict]:
        """Configuração de todas as fontes: `{"idealista": {...}, "imovirtual": {...}}`."""
        dados = self._ler_config_bruta()
        config = {}
        for fonte, info in FONTES.items():
            override = dados.get(fonte)
            override = override if isinstance(override, dict) else {}
            config[fonte] = {
                "url_default": info["url_default"],
                "url_atual": override.get("url_atual") or info["url_default"],
            }
        return config

    def guardar_url_atual(self, fonte: str, url: str) -> dict:
        self._validar_fonte(fonte)
        dados = self._ler_config_bruta()
        dados[fonte] = {"url_atual": url}
        self._write_json(self.config_path, dados)
        return self.carregar_config()[fonte]

    def resetar_url(self, fonte: str) -> dict:
        self._validar_fonte(fonte)
        dados = self._ler_config_bruta()
        dados[fonte] = {"url_atual": None}
        self._write_json(self.config_path, dados)
        return self.carregar_config()[fonte]

    # ---- Favoritos (partilhados entre fontes) --------------------------------

    def carregar_favoritos(self) -> set[str]:
        dados = self._read_json(self.favoritos_path, [])
        if isinstance(dados, list):
            return {str(item) for item in dados}
        return set()

    def guardar_favoritos(self, favoritos: set[str]) -> None:
        self._write_json(self.favoritos_path, sorted(favoritos))

    def alternar_favorito(self, link: str) -> bool:
        favoritos = self.carregar_favoritos()
        if link in favoritos:
            favoritos.discard(link)
            is_favorito = False
        else:
            favoritos.add(link)
            is_favorito = True
        self.guardar_favoritos(favoritos)
        return is_favorito

    # ---- Ocultos (anúncios escondidos da listagem, partilhados entre fontes) --

    def carregar_ocultos(self) -> set[str]:
        dados = self._read_json(self.ocultos_path, [])
        if isinstance(dados, list):
            return {str(item) for item in dados}
        return set()

    def guardar_ocultos(self, ocultos: set[str]) -> None:
        self._write_json(self.ocultos_path, sorted(ocultos))

    def alternar_oculto(self, link: str) -> bool:
        """Oculta/reexibe um anúncio na interface, sem apagar nada do backend."""
        ocultos = self.carregar_ocultos()
        if link in ocultos:
            ocultos.discard(link)
            is_oculto = False
        else:
            ocultos.add(link)
            is_oculto = True
        self.guardar_ocultos(ocultos)
        return is_oculto

    # ---- Log ------------------------------------------------------------------

    def log_mensagem(self, mensagem: str) -> None:
        self.ensure_dir()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        linha = f"[{timestamp}] {mensagem}\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(linha)
        print(mensagem)


default_storage = Storage(BASE_DIR / "data")
