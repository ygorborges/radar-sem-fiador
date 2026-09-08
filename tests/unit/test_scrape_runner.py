"""Testes do gestor de execuções em segundo plano (ScrapeJobManager)."""
import threading
import time

import pytest

from scrape_runner import ScrapeJobManager, criar_job_managers_padrao
from storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


def test_estado_inicial_e_idle(store):
    manager = ScrapeJobManager("idealista", run_coroutine=None, store=store)
    assert manager.status()["state"] == "idle"


def test_start_conclui_com_sucesso(store):
    async def fake_run(url, store=None, progress_callback=None):
        return [{"titulo": "Anúncio 1", "link": url}, {"titulo": "Anúncio 2", "link": url}]

    manager = ScrapeJobManager("idealista", run_coroutine=fake_run, store=store)
    status = manager.start("https://www.idealista.pt/busca/")
    assert status["state"] == "running"
    assert status["url"] == "https://www.idealista.pt/busca/"

    manager._thread.join(timeout=5)

    final_status = manager.status()
    assert final_status["state"] == "done"
    assert final_status["total_encontrados"] == 2
    assert "Concluído" in final_status["mensagem"]
    # Progresso é limpo ao concluir; a UI não deve mostrar uma ETA obsoleta.
    assert final_status["eta_segundos"] is None


def test_progresso_e_reportado_durante_a_execucao(store):
    marcos_capturados = []

    async def fake_run_com_progresso(url, store=None, progress_callback=None):
        for i in range(1, 4):
            progress_callback(i, 3)
            marcos_capturados.append(manager.status()["atual"])
        return [{"link": url}]

    manager = ScrapeJobManager("idealista", fake_run_com_progresso, store=store)
    manager.start("https://www.idealista.pt/busca/")
    manager._thread.join(timeout=5)

    assert marcos_capturados == [1, 2, 3]
    # Depois de concluído, atual/total refletem o último anúncio processado.
    final_status = manager.status()
    assert final_status["state"] == "done"


def test_eta_diminui_conforme_o_progresso_avanca(store):
    async def fake_run_lento(url, store=None, progress_callback=None):
        progress_callback(1, 4)
        time.sleep(0.05)
        progress_callback(2, 4)
        time.sleep(0.2)  # dá tempo do teste observar o estado "running" com ETA antes de concluir
        return []

    manager = ScrapeJobManager("idealista", fake_run_lento, store=store)
    manager.start("https://www.idealista.pt/busca/")

    # Espera o segundo tick de progresso acontecer.
    for _ in range(200):
        if manager.status()["atual"] == 2:
            break
        time.sleep(0.01)

    status = manager.status()
    assert status["atual"] == 2
    assert status["total"] == 4
    assert status["eta_segundos"] is not None
    assert status["eta_segundos"] >= 0

    manager._thread.join(timeout=5)


def test_start_com_erro_marca_estado_error(store):
    async def fake_run_falhando(url, store=None, progress_callback=None):
        raise RuntimeError("Falha simulada de rede")

    manager = ScrapeJobManager("idealista", run_coroutine=fake_run_falhando, store=store)
    manager.start("https://www.idealista.pt/busca/")
    manager._thread.join(timeout=5)

    final_status = manager.status()
    assert final_status["state"] == "error"
    assert "Falha simulada de rede" in final_status["mensagem"]


def test_start_enquanto_em_execucao_nao_dispara_segundo_job(store):
    liberar = threading.Event()
    chamadas = []

    async def fake_run_bloqueante(url, store=None, progress_callback=None):
        chamadas.append(url)
        # Simula trabalho demorado até o teste liberar explicitamente.
        while not liberar.is_set():
            time.sleep(0.01)
        return []

    manager = ScrapeJobManager("idealista", run_coroutine=fake_run_bloqueante, store=store)
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


def test_criar_job_managers_padrao_tem_um_por_fonte(store):
    managers = criar_job_managers_padrao(store=store)
    assert set(managers.keys()) == {"idealista", "imovirtual"}
    assert all(isinstance(m, ScrapeJobManager) for m in managers.values())


def test_fontes_diferentes_executam_de_forma_independente(store):
    liberar_idealista = threading.Event()

    async def fake_idealista(url, store=None, progress_callback=None):
        liberar_idealista.wait(timeout=5)
        return [{"link": url}]

    async def fake_imovirtual(url, store=None, progress_callback=None):
        return [{"link": url}, {"link": url + "/2"}]

    manager_idealista = ScrapeJobManager("idealista", fake_idealista, store=store)
    manager_imovirtual = ScrapeJobManager("imovirtual", fake_imovirtual, store=store)

    status_idealista = manager_idealista.start("https://www.idealista.pt/busca/")
    assert status_idealista["state"] == "running"

    # O imovirtual roda e conclui normalmente enquanto o idealista continua preso.
    manager_imovirtual.start("https://www.imovirtual.com/pt/resultados/")
    manager_imovirtual._thread.join(timeout=5)
    assert manager_imovirtual.status()["state"] == "done"
    assert manager_idealista.status()["state"] == "running"

    liberar_idealista.set()
    manager_idealista._thread.join(timeout=5)
    assert manager_idealista.status()["state"] == "done"
