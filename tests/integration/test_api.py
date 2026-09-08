"""Testes de integração da API Flask (app.py) usando o test client."""
import threading

import pytest

from app import create_app
from scrape_runner import ScrapeJobManager
from storage import Storage, URL_BASE_DEFAULT


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


@pytest.fixture
def client(store):
    job_manager = ScrapeJobManager(run_coroutine=None, store=store)
    app = create_app(job_manager=job_manager, store=store)
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


def test_get_results_inclui_flag_favorito(client, store):
    store.guardar_resultados([
        {"titulo": "Anúncio A", "link": "https://a.pt/1"},
        {"titulo": "Anúncio B", "link": "https://a.pt/2"},
    ])
    store.alternar_favorito("https://a.pt/1")

    response = client.get("/api/results")
    dados = {item["link"]: item["favorito"] for item in response.get_json()}
    assert dados == {"https://a.pt/1": True, "https://a.pt/2": False}


def test_get_config_retorna_padrao_por_omissao(client):
    response = client.get("/api/config")
    config = response.get_json()
    assert config["url_default"] == URL_BASE_DEFAULT
    assert config["url_atual"] == URL_BASE_DEFAULT
    assert config["is_default"] is True


def test_post_config_atualiza_url_atual_sem_alterar_default(client):
    nova_url = "https://www.idealista.pt/areas/arrendar-casas/porto-centro/"
    response = client.post("/api/config", json={"url": nova_url})
    assert response.status_code == 200
    config = response.get_json()
    assert config["url_atual"] == nova_url
    assert config["url_default"] == URL_BASE_DEFAULT
    assert config["is_default"] is False


def test_post_config_rejeita_url_vazia(client):
    response = client.post("/api/config", json={"url": "  "})
    assert response.status_code == 400
    assert "erro" in response.get_json()


def test_post_config_rejeita_dominio_diferente_de_idealista(client):
    response = client.post("/api/config", json={"url": "https://outrosite.com/busca"})
    assert response.status_code == 400
    assert "erro" in response.get_json()


def test_post_config_reset_restaura_padrao(client):
    client.post("/api/config", json={"url": "https://www.idealista.pt/outra-busca/"})
    response = client.post("/api/config/reset")
    config = response.get_json()
    assert config["url_atual"] == URL_BASE_DEFAULT
    assert config["is_default"] is True


def test_toggle_favorito_reflete_em_get_results(client, store):
    store.guardar_resultados([{"titulo": "Anúncio A", "link": "https://a.pt/1"}])

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


def test_scrape_status_inicial_e_idle(client):
    response = client.get("/api/scrape/status")
    assert response.get_json()["state"] == "idle"


def test_post_scrape_dispara_job_e_conclui(store):
    async def fake_run(url, store=None):
        return [{"titulo": "Anúncio", "link": url}]

    job_manager = ScrapeJobManager(run_coroutine=fake_run, store=store)
    app = create_app(job_manager=job_manager, store=store)
    app.testing = True
    client = app.test_client()

    response = client.post("/api/scrape")
    assert response.status_code == 202
    assert response.get_json()["state"] == "running"
    assert response.get_json()["url"] == URL_BASE_DEFAULT

    job_manager._thread.join(timeout=5)

    status = client.get("/api/scrape/status").get_json()
    assert status["state"] == "done"
    assert status["total_encontrados"] == 1


def test_post_scrape_enquanto_em_execucao_retorna_409(store):
    liberar = threading.Event()

    async def fake_run_bloqueante(url, store=None):
        liberar.wait(timeout=5)
        return []

    job_manager = ScrapeJobManager(run_coroutine=fake_run_bloqueante, store=store)
    app = create_app(job_manager=job_manager, store=store)
    app.testing = True
    client = app.test_client()

    primeira = client.post("/api/scrape")
    assert primeira.status_code == 202

    segunda = client.post("/api/scrape")
    assert segunda.status_code == 409

    liberar.set()
    job_manager._thread.join(timeout=5)
