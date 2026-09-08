"""Execução do scraper em segundo plano, sem bloquear o servidor web.

O Playwright (`scraper.raspar_idealista_porto`) é assíncrono e demorado, e o
Flask atende pedidos de forma síncrona. Para que o botão "Executar scraper"
da interface não trave o servidor, a varredura corre numa thread separada
dentro do mesmo processo, com o estado exposto via `status()` para a UI
fazer polling.
"""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Awaitable, Callable, Optional

import scraper
from storage import Storage, default_storage

RunCoroutine = Callable[..., Awaitable[list[dict]]]


class ScrapeJobManager:
    """Garante no máximo uma execução do scraper por vez, numa thread própria."""

    def __init__(self, run_coroutine: Optional[RunCoroutine] = None, store: Optional[Storage] = None):
        self._run_coroutine = run_coroutine or scraper.raspar_idealista_porto
        self._store = store or default_storage
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._status: dict = {
            "state": "idle",  # idle | running | done | error
            "url": None,
            "started_at": None,
            "finished_at": None,
            "total_encontrados": None,
            "total_acumulado": None,
            "mensagem": None,
        }

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self, url: str) -> dict:
        with self._lock:
            if self._status["state"] == "running":
                return dict(self._status)
            self._status = {
                "state": "running",
                "url": url,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": None,
                "total_encontrados": None,
                "total_acumulado": None,
                "mensagem": "Scraper em execução...",
            }

        self._thread = threading.Thread(target=self._run, args=(url,), daemon=True)
        self._thread.start()
        return self.status()

    def _run(self, url: str) -> None:
        try:
            resultados = asyncio.run(self._run_coroutine(url, store=self._store))
            total_acumulado = len(self._store.carregar_resultados())
            with self._lock:
                self._status.update({
                    "state": "done",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "total_encontrados": len(resultados),
                    "total_acumulado": total_acumulado,
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
                    "mensagem": f"Erro durante o scraping: {exc}",
                })


default_job_manager = ScrapeJobManager()
