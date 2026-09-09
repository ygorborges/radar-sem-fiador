"""Execução dos scrapers em segundo plano, sem bloquear o servidor web.

O Playwright é assíncrono e demorado, e o Flask atende pedidos de forma
síncrona. Para que o botão "Executar scraper" da interface não trave o
servidor, cada varredura corre numa thread separada dentro do mesmo
processo, com o estado exposto via `status()` para a UI fazer polling.

Cada fonte (idealista, imovirtual, ...) tem o seu próprio `ScrapeJobManager`
— duas fontes podem varrer ao mesmo tempo sem interferir uma na outra; só
não é possível disparar duas execuções da *mesma* fonte simultaneamente.
"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime
from typing import Awaitable, Callable, Optional

import scraper
import scraper_imovirtual
import verificador_disponibilidade
from storage import Storage, default_storage

RunCoroutine = Callable[..., Awaitable[list[dict]]]
CheckCoroutine = Callable[..., Awaitable[list[dict]]]


class ScrapeJobManager:
    """Garante no máximo uma execução do scraper por vez, numa thread própria."""

    def __init__(self, fonte: str, run_coroutine: RunCoroutine, store: Optional[Storage] = None):
        self._fonte = fonte
        self._run_coroutine = run_coroutine
        self._store = store or default_storage
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        # Marca temporal (time.monotonic, imune a ajustes de relógio) de quando
        # o primeiro anúncio começou a ser processado nesta execução — usada
        # para estimar o tempo restante a partir do ritmo real observado.
        self._progresso_inicio: Optional[float] = None
        self._status: dict = self._status_ocioso()

    @staticmethod
    def _status_ocioso() -> dict:
        return {
            "state": "idle",  # idle | running | done | error
            "url": None,
            "started_at": None,
            "finished_at": None,
            "total_encontrados": None,
            "total_acumulado": None,
            "mensagem": None,
            "atual": None,
            "total": None,
            "eta_segundos": None,
        }

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self, url: str) -> dict:
        with self._lock:
            if self._status["state"] == "running":
                return dict(self._status)
            self._progresso_inicio = None
            self._status = self._status_ocioso()
            self._status.update({
                "state": "running",
                "url": url,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "mensagem": "Coletando lista de anúncios...",
            })

        self._thread = threading.Thread(target=self._run, args=(url,), daemon=True)
        self._thread.start()
        return self.status()

    def _atualizar_progresso(self, atual: int, total: int) -> None:
        agora = time.monotonic()
        with self._lock:
            if self._status["state"] != "running":
                return
            if self._progresso_inicio is None:
                self._progresso_inicio = agora

            eta_segundos = None
            if atual > 0 and total > 0:
                decorrido = agora - self._progresso_inicio
                ritmo_por_anuncio = decorrido / atual
                eta_segundos = round(ritmo_por_anuncio * (total - atual))

            self._status.update({
                "atual": atual,
                "total": total,
                "eta_segundos": eta_segundos,
                "mensagem": f"Analisando anúncio {atual} de {total}...",
            })

    def _run(self, url: str) -> None:
        try:
            resultados = asyncio.run(
                self._run_coroutine(url, store=self._store, progress_callback=self._atualizar_progresso)
            )
            total_acumulado = len(self._store.carregar_resultados(self._fonte))
            with self._lock:
                self._status.update({
                    "state": "done",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "total_encontrados": len(resultados),
                    "total_acumulado": total_acumulado,
                    "eta_segundos": None,
                    "mensagem": (
                        f"Concluído: {len(resultados)} anúncio(s) novo(s) nesta execução "
                        f"({total_acumulado} no total)."
                    ),
                })
        except Exception as exc:  # pragma: no cover - caminho defensivo
            with self._lock:
                self._status.update({
                    "state": "error",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "eta_segundos": None,
                    "mensagem": f"Erro durante o scraping: {exc}",
                })


def criar_job_managers_padrao(store: Optional[Storage] = None) -> dict[str, ScrapeJobManager]:
    """Cria um `ScrapeJobManager` por fonte suportada."""
    return {
        "idealista": ScrapeJobManager("idealista", scraper.raspar_idealista_porto, store=store),
        "imovirtual": ScrapeJobManager("imovirtual", scraper_imovirtual.raspar_imovirtual, store=store),
    }


default_job_managers = criar_job_managers_padrao()


class VerificacaoJobManager:
    """Garante no máximo uma verificação de disponibilidade por vez, por fonte.

    Espelha o `ScrapeJobManager` (mesmo modelo de thread única + polling de
    status), mas para revisitar anúncios já coletados e remover
    definitivamente os que saíram do ar (arrendados ou removidos pelo
    anunciante), via `Storage.remover_resultado`.
    """

    def __init__(self, fonte: str, run_coroutine: CheckCoroutine, store: Optional[Storage] = None):
        self._fonte = fonte
        self._run_coroutine = run_coroutine
        self._store = store or default_storage
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._progresso_inicio: Optional[float] = None
        self._status: dict = self._status_ocioso()

    @staticmethod
    def _status_ocioso() -> dict:
        return {
            "state": "idle",  # idle | running | done | error
            "started_at": None,
            "finished_at": None,
            "total_verificados": None,
            "total_removidos": None,
            "mensagem": None,
            "atual": None,
            "total": None,
            "eta_segundos": None,
        }

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self) -> dict:
        with self._lock:
            if self._status["state"] == "running":
                return dict(self._status)
            self._progresso_inicio = None
            self._status = self._status_ocioso()
            self._status.update({
                "state": "running",
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "mensagem": "Verificando anúncios já coletados...",
            })

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self.status()

    def _atualizar_progresso(self, atual: int, total: int) -> None:
        agora = time.monotonic()
        with self._lock:
            if self._status["state"] != "running":
                return
            if self._progresso_inicio is None:
                self._progresso_inicio = agora

            eta_segundos = None
            if atual > 0 and total > 0:
                decorrido = agora - self._progresso_inicio
                ritmo_por_anuncio = decorrido / atual
                eta_segundos = round(ritmo_por_anuncio * (total - atual))

            self._status.update({
                "atual": atual,
                "total": total,
                "eta_segundos": eta_segundos,
                "mensagem": f"Verificando anúncio {atual} de {total}...",
            })

    def _run(self) -> None:
        try:
            removidos = asyncio.run(
                self._run_coroutine(self._fonte, store=self._store, progress_callback=self._atualizar_progresso)
            )
            with self._lock:
                total = self._status.get("total") or 0
                self._status.update({
                    "state": "done",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "total_verificados": total,
                    "total_removidos": len(removidos),
                    "eta_segundos": None,
                    "mensagem": (
                        f"Concluído: {len(removidos)} anúncio(s) removido(s) da lista (fora do ar) "
                        f"de {total} verificado(s)."
                    ),
                })
        except Exception as exc:  # pragma: no cover - caminho defensivo
            with self._lock:
                self._status.update({
                    "state": "error",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "eta_segundos": None,
                    "mensagem": f"Erro durante a verificação: {exc}",
                })


def criar_verificacao_managers_padrao(store: Optional[Storage] = None) -> dict[str, VerificacaoJobManager]:
    """Cria um `VerificacaoJobManager` por fonte suportada."""
    return {
        "idealista": VerificacaoJobManager("idealista", verificador_disponibilidade.verificar_disponibilidade, store=store),
        "imovirtual": VerificacaoJobManager("imovirtual", verificador_disponibilidade.verificar_disponibilidade, store=store),
    }


default_check_managers = criar_verificacao_managers_padrao()
