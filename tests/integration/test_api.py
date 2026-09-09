"""Testes de integração da API Flask (app.py) usando o test client."""
import threading

import pytest

from app import create_app
from scrape_runner import ScrapeJobManager, VerificacaoJobManager
from storage import URL_BASE_DEFAULT_IDEALISTA, URL_BASE_DEFAULT_IMOVIRTUAL, Storage


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


@pytest.fixture
def job_managers(store):
    return {
        "idealista": ScrapeJobManager("idealista", run_coroutine=None, store=store),
        "imovirtual": ScrapeJobManager("imovirtual", run_coroutine=None, store=store),
    }


@pytest.fixture
def check_managers(store):
    return {
        "idealista": VerificacaoJobManager("idealista", run_coroutine=None, store=store),
        "imovirtual": VerificacaoJobManager("imovirtual", run_coroutine=None, store=store),
    }


@pytest.fixture
def client(store, job_managers, check_managers):
    app = create_app(job_managers=job_managers, check_managers=check_managers, store=store)
    app.testing = True
    return app.test_client()


def test_index_serve_a_pagina_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Oportunidades de arrendamento" in response.data


def test_get_results_vazio_inicialmente(client):
    response = client.get("/api/results")
    assert response.status_code == 200
    assert response.get_json() == []


def test_get_results_combina_todas_as_fontes_com_a_flag_favorito(client, store):
    store.guardar_resultados("idealista", [{"titulo": "Anúncio A", "link": "https://a.pt/1"}])
    store.guardar_resultados("imovirtual", [{"titulo": "Anúncio B", "link": "https://b.pt/1"}])
    store.alternar_favorito("https://a.pt/1")

    resultados = client.get("/api/results").get_json()
    por_link = {item["link"]: item for item in resultados}

    assert por_link["https://a.pt/1"]["fonte"] == "idealista"
    assert por_link["https://a.pt/1"]["favorito"] is True
    assert por_link["https://b.pt/1"]["fonte"] == "imovirtual"
    assert por_link["https://b.pt/1"]["favorito"] is False


def test_get_results_marca_a_flag_oculto(client, store):
    store.guardar_resultados("idealista", [{"titulo": "Anúncio A", "link": "https://a.pt/1"}])
    store.alternar_oculto("https://a.pt/1")

    resultados = client.get("/api/results").get_json()
    assert resultados[0]["oculto"] is True


def test_get_config_retorna_todas_as_fontes(client):
    config = client.get("/api/config").get_json()

    assert config["idealista"]["url_default"] == URL_BASE_DEFAULT_IDEALISTA
    assert config["idealista"]["url_atual"] == URL_BASE_DEFAULT_IDEALISTA
    assert config["idealista"]["is_default"] is True
    assert config["idealista"]["label"]

    assert config["imovirtual"]["url_default"] == URL_BASE_DEFAULT_IMOVIRTUAL
    assert config["imovirtual"]["is_default"] is True


def test_post_config_atualiza_url_atual_sem_alterar_default(client):
    nova_url = "https://www.idealista.pt/areas/arrendar-casas/porto-centro/"
    response = client.post("/api/config/idealista", json={"url": nova_url})
    assert response.status_code == 200
    config = response.get_json()
    assert config["url_atual"] == nova_url
    assert config["url_default"] == URL_BASE_DEFAULT_IDEALISTA
    assert config["is_default"] is False

    # A outra fonte não é afetada.
    config_geral = client.get("/api/config").get_json()
    assert config_geral["imovirtual"]["url_atual"] == URL_BASE_DEFAULT_IMOVIRTUAL


def test_post_config_fonte_desconhecida_retorna_404(client):
    response = client.post("/api/config/olx", json={"url": "https://www.olx.pt/busca/"})
    assert response.status_code == 404


def test_post_config_rejeita_url_vazia(client):
    response = client.post("/api/config/idealista", json={"url": "  "})
    assert response.status_code == 400
    assert "erro" in response.get_json()


def test_post_config_rejeita_dominio_de_outra_fonte(client):
    # URL válida do Imovirtual não pode ser aceite como busca do idealista.
    response = client.post("/api/config/idealista", json={"url": URL_BASE_DEFAULT_IMOVIRTUAL})
    assert response.status_code == 400
    assert "erro" in response.get_json()


def test_post_config_reset_restaura_padrao(client):
    client.post("/api/config/idealista", json={"url": "https://www.idealista.pt/outra-busca/"})
    response = client.post("/api/config/idealista/reset")
    config = response.get_json()
    assert config["url_atual"] == URL_BASE_DEFAULT_IDEALISTA
    assert config["is_default"] is True


def test_toggle_favorito_reflete_em_get_results(client, store):
    store.guardar_resultados("idealista", [{"titulo": "Anúncio A", "link": "https://a.pt/1"}])

    response = client.post("/api/favorites/toggle", json={"link": "https://a.pt/1"})
    assert response.status_code == 200
    assert response.get_json() == {"link": "https://a.pt/1", "favorito": True}

    resultados = client.get("/api/results").get_json()
    assert resultados[0]["favorito"] is True

    response = client.post("/api/favorites/toggle", json={"link": "https://a.pt/1"})
    assert response.get_json()["favorito"] is False


def test_toggle_favorito_sem_link_retorna_erro(client):
    response = client.post("/api/favorites/toggle", json={})
    assert response.status_code == 400


def test_toggle_oculto_reflete_em_get_results(client, store):
    store.guardar_resultados("idealista", [{"titulo": "Anúncio A", "link": "https://a.pt/1"}])

    response = client.post("/api/hidden/toggle", json={"link": "https://a.pt/1"})
    assert response.status_code == 200
    assert response.get_json() == {"link": "https://a.pt/1", "oculto": True}

    resultados = client.get("/api/results").get_json()
    assert resultados[0]["oculto"] is True

    response = client.post("/api/hidden/toggle", json={"link": "https://a.pt/1"})
    assert response.get_json()["oculto"] is False


def test_toggle_oculto_sem_link_retorna_erro(client):
    response = client.post("/api/hidden/toggle", json={})
    assert response.status_code == 400


def test_list_hidden_retorna_links_ocultos(client, store):
    store.alternar_oculto("https://a.pt/1")
    store.alternar_oculto("https://a.pt/2")
    assert client.get("/api/hidden").get_json() == ["https://a.pt/1", "https://a.pt/2"]


def test_scrape_status_inicial_e_idle_para_todas_as_fontes(client):
    status = client.get("/api/scrape/status").get_json()
    assert status["idealista"]["state"] == "idle"
    assert status["imovirtual"]["state"] == "idle"


def test_post_scrape_fonte_desconhecida_retorna_404(client):
    response = client.post("/api/scrape/olx")
    assert response.status_code == 404


def test_post_scrape_dispara_job_e_conclui(store):
    async def fake_run(url, store=None, progress_callback=None):
        return [{"titulo": "Anúncio", "link": url}]

    job_managers = {
        "idealista": ScrapeJobManager("idealista", fake_run, store=store),
        "imovirtual": ScrapeJobManager("imovirtual", run_coroutine=None, store=store),
    }
    app = create_app(job_managers=job_managers, store=store)
    app.testing = True
    client = app.test_client()

    response = client.post("/api/scrape/idealista")
    assert response.status_code == 202
    assert response.get_json()["state"] == "running"
    assert response.get_json()["url"] == URL_BASE_DEFAULT_IDEALISTA

    job_managers["idealista"]._thread.join(timeout=5)

    status = client.get("/api/scrape/status").get_json()
    assert status["idealista"]["state"] == "done"
    assert status["idealista"]["total_encontrados"] == 1
    # A outra fonte continua parada, intocada.
    assert status["imovirtual"]["state"] == "idle"


def test_post_scrape_enquanto_em_execucao_retorna_409(store):
    liberar = threading.Event()

    async def fake_run_bloqueante(url, store=None, progress_callback=None):
        liberar.wait(timeout=5)
        return []

    job_managers = {
        "idealista": ScrapeJobManager("idealista", fake_run_bloqueante, store=store),
        "imovirtual": ScrapeJobManager("imovirtual", run_coroutine=None, store=store),
    }
    app = create_app(job_managers=job_managers, store=store)
    app.testing = True
    client = app.test_client()

    primeira = client.post("/api/scrape/idealista")
    assert primeira.status_code == 202

    segunda = client.post("/api/scrape/idealista")
    assert segunda.status_code == 409

    liberar.set()
    job_managers["idealista"]._thread.join(timeout=5)


def test_check_status_inicial_e_idle_para_todas_as_fontes(client):
    status = client.get("/api/check/status").get_json()
    assert status["idealista"]["state"] == "idle"
    assert status["imovirtual"]["state"] == "idle"


def test_post_check_fonte_desconhecida_retorna_404(client):
    response = client.post("/api/check/olx")
    assert response.status_code == 404


def test_post_check_dispara_job_e_conclui(store):
    async def fake_check(fonte, store=None, progress_callback=None):
        return [{"titulo": "Anúncio", "link": "https://a.pt/1"}]

    check_managers = {
        "idealista": VerificacaoJobManager("idealista", fake_check, store=store),
        "imovirtual": VerificacaoJobManager("imovirtual", run_coroutine=None, store=store),
    }
    app = create_app(check_managers=check_managers, store=store)
    app.testing = True
    client = app.test_client()

    response = client.post("/api/check/idealista")
    assert response.status_code == 202
    assert response.get_json()["state"] == "running"

    check_managers["idealista"]._thread.join(timeout=5)

    status = client.get("/api/check/status").get_json()
    assert status["idealista"]["state"] == "done"
    assert status["idealista"]["total_removidos"] == 1
    assert status["imovirtual"]["state"] == "idle"


def test_post_check_enquanto_em_execucao_retorna_409(store):
    liberar = threading.Event()

    async def fake_check_bloqueante(fonte, store=None, progress_callback=None):
        liberar.wait(timeout=5)
        return []

    check_managers = {
        "idealista": VerificacaoJobManager("idealista", fake_check_bloqueante, store=store),
        "imovirtual": VerificacaoJobManager("imovirtual", run_coroutine=None, store=store),
    }
    app = create_app(check_managers=check_managers, store=store)
    app.testing = True
    client = app.test_client()

    primeira = client.post("/api/check/idealista")
    assert primeira.status_code == 202

    segunda = client.post("/api/check/idealista")
    assert segunda.status_code == 409

    liberar.set()
    check_managers["idealista"]._thread.join(timeout=5)


def test_scrape_de_fontes_diferentes_nao_bloqueia_uma_a_outra(store):
    liberar_idealista = threading.Event()

    async def fake_idealista(url, store=None, progress_callback=None):
        liberar_idealista.wait(timeout=5)
        return []

    async def fake_imovirtual(url, store=None, progress_callback=None):
        return [{"titulo": "Anúncio", "link": url}]

    job_managers = {
        "idealista": ScrapeJobManager("idealista", fake_idealista, store=store),
        "imovirtual": ScrapeJobManager("imovirtual", fake_imovirtual, store=store),
    }
    app = create_app(job_managers=job_managers, store=store)
    app.testing = True
    client = app.test_client()

    assert client.post("/api/scrape/idealista").status_code == 202
    # Mesmo com o idealista ainda a correr, o imovirtual pode ser disparado.
    assert client.post("/api/scrape/imovirtual").status_code == 202

    job_managers["imovirtual"]._thread.join(timeout=5)
    status = client.get("/api/scrape/status").get_json()
    assert status["imovirtual"]["state"] == "done"
    assert status["idealista"]["state"] == "running"

    liberar_idealista.set()
    job_managers["idealista"]._thread.join(timeout=5)
