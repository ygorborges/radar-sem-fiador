"""Testes do gestor de execuções em segundo plano (ScrapeJobManager)."""
import threading
import time

import pytest

from scrape_runner import ScrapeJobManager
from storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


def test_estado_inicial_e_idle(store):
    manager = ScrapeJobManager(run_coroutine=None, store=store)
    assert manager.status()["state"] == "idle"


def test_start_conclui_com_sucesso(store):
    async def fake_run(url, store=None):
        return [{"titulo": "Anúncio 1", "link": url}, {"titulo": "Anúncio 2", "link": url}]

    manager = ScrapeJobManager(run_coroutine=fake_run, store=store)
    status = manager.start("https://www.idealista.pt/busca/")
    assert status["state"] == "running"
    assert status["url"] == "https://www.idealista.pt/busca/"

    manager._thread.join(timeout=5)

    final_status = manager.status()
    assert final_status["state"] == "done"
    assert final_status["total_encontrados"] == 2
    assert "Concluído" in final_status["mensagem"]


def test_start_com_erro_marca_estado_error(store):
    async def fake_run_falhando(url, store=None):
        raise RuntimeError("Falha simulada de rede")

    manager = ScrapeJobManager(run_coroutine=fake_run_falhando, store=store)
    manager.start("https://www.idealista.pt/busca/")
    manager._thread.join(timeout=5)

    final_status = manager.status()
    assert final_status["state"] == "error"
    assert "Falha simulada de rede" in final_status["mensagem"]


def test_start_enquanto_em_execucao_nao_dispara_segundo_job(store):
    liberar = threading.Event()
    chamadas = []

    async def fake_run_bloqueante(url, store=None):
        chamadas.append(url)
        # Simula trabalho demorado até o teste liberar explicitamente.
        while not liberar.is_set():
            time.sleep(0.01)
        return []

    manager = ScrapeJobManager(run_coroutine=fake_run_bloqueante, store=store)
    primeiro_status = manager.start("https://www.idealista.pt/busca-1/")
    assert primeiro_status["state"] == "running"

    # Aguarda a thread realmente começar a rodar a coroutine.
    for _ in range(200):
        if chamadas:
            break
        time.sleep(0.01)

    segundo_status = manager.start("https://www.idealista.pt/busca-2/")
    assert segundo_status["state"] == "running"
    assert segundo_status["url"] == "https://www.idealista.pt/busca-1/"
    assert chamadas == ["https://www.idealista.pt/busca-1/"]

    liberar.set()
    manager._thread.join(timeout=5)
    assert manager.status()["state"] == "done"
