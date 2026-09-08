"""Persistência em JSON usada pelo scraper e pela API web.

Centraliza toda a leitura/escrita de ficheiros em `data/` (histórico,
resultados, configuração da URL de busca e favoritos) para que tanto o
scraper quanto a aplicação Flask usem a mesma fonte de verdade.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent

URL_BASE_DEFAULT = (
    "https://www.idealista.pt/areas/arrendar-casas/com-preco-max_999,tamanho-min_60,"
    "apartamentos,t1,t2,t3,t4-t5,arrendamento-longa-duracao/"
    "?shape=%28%28_tdzFp%7Cxs%40goBglAaC%7BhFvz%40ceCbpBmEdyE%7Ci%40xPjzB%7DbAb%7C%40c%7BAlSkc%40vlDc_B%60%5D%29%29"
    "&ordem=precos-asc"
)


class Storage:
    """Acesso aos ficheiros JSON/log de uma pasta `data/` específica.

    Recebe o diretório de dados no construtor (em vez de usar um caminho
    fixo) para que os testes possam apontar para uma pasta temporária sem
    tocar nos dados reais do utilizador.
    """

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.historico_path = self.data_dir / "historico_anuncios.json"
        self.resultados_path = self.data_dir / "resultados_idealista.json"
        self.config_path = self.data_dir / "config.json"
        self.favoritos_path = self.data_dir / "favoritos.json"
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

    # ---- Histórico de anúncios já visitados --------------------------------

    def carregar_historico(self) -> set[str]:
        dados = self._read_json(self.historico_path, [])
        if isinstance(dados, list):
            return {str(item) for item in dados}
        return set()

    def guardar_historico(self, historico: set[str]) -> None:
        self._write_json(self.historico_path, sorted(historico))

    # ---- Resultados da última varredura ------------------------------------

    def carregar_resultados(self) -> list[dict]:
        dados = self._read_json(self.resultados_path, [])
        return dados if isinstance(dados, list) else []

    def guardar_resultados(self, resultados: list[dict]) -> None:
        self._write_json(self.resultados_path, resultados)

    def atualizar_resultados(self, novos: list[dict]) -> list[dict]:
        """Mescla `novos` aos resultados já guardados, por `link`.

        Cada execução do scraper só revisita anúncios que ainda não estão no
        histórico, então uma simples sobrescrita apagaria os achados de
        execuções anteriores. Aqui, anúncios repetidos são atualizados no
        lugar e os demais são preservados; novos anúncios são anexados.
        """
        existentes = self.carregar_resultados()
        indice = {item.get("link"): pos for pos, item in enumerate(existentes) if item.get("link")}

        for item in novos:
            link = item.get("link")
            if link and link in indice:
                existentes[indice[link]] = item
            else:
                existentes.append(item)
                if link:
                    indice[link] = len(existentes) - 1

        self.guardar_resultados(existentes)
        return existentes

    # ---- Configuração da URL de busca --------------------------------------

    def carregar_config(self) -> dict:
        dados = self._read_json(self.config_path, {})
        if not isinstance(dados, dict):
            dados = {}
        return {
            "url_default": URL_BASE_DEFAULT,
            "url_atual": dados.get("url_atual") or URL_BASE_DEFAULT,
        }

    def guardar_url_atual(self, url: str) -> dict:
        self._write_json(self.config_path, {"url_atual": url})
        return self.carregar_config()

    def resetar_url(self) -> dict:
        self._write_json(self.config_path, {"url_atual": None})
        return self.carregar_config()

    # ---- Favoritos ----------------------------------------------------------

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

    # ---- Log ------------------------------------------------------------------

    def log_mensagem(self, mensagem: str) -> None:
        self.ensure_dir()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        linha = f"[{timestamp}] {mensagem}\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(linha)
        print(mensagem)


default_storage = Storage(BASE_DIR / "data")
