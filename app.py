"""Aplicação web do RadarSemFiador.

Processo único que serve a interface (`static/index.html`) e expõe uma API
para configurar a URL de busca, disparar o scraper e favoritar anúncios.
Substitui o antigo par `scraper.py` + `serve_ui.py`: agora basta rodar
`python app.py`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from scrape_runner import ScrapeJobManager, default_job_manager
from storage import Storage, default_storage

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def create_app(
    job_manager: Optional[ScrapeJobManager] = None,
    store: Optional[Storage] = None,
) -> Flask:
    """Cria a aplicação Flask. Aceita `job_manager`/`store` para testes isolados."""
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.config["JOB_MANAGER"] = job_manager or default_job_manager
    app.config["STORE"] = store or default_storage

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/results")
    def get_results():
        store = app.config["STORE"]
        resultados = store.carregar_resultados()
        favoritos = store.carregar_favoritos()
        for item in resultados:
            item["favorito"] = item.get("link") in favoritos
        return jsonify(resultados)

    @app.get("/api/config")
    def get_config():
        store = app.config["STORE"]
        config = store.carregar_config()
        config["is_default"] = config["url_atual"] == config["url_default"]
        return jsonify(config)

    @app.post("/api/config")
    def update_config():
        store = app.config["STORE"]
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return jsonify({"erro": "A URL não pode estar vazia."}), 400
        if not url.startswith("https://www.idealista.pt"):
            return jsonify({"erro": "A URL deve ser uma busca do idealista.pt."}), 400
        config = store.guardar_url_atual(url)
        config["is_default"] = config["url_atual"] == config["url_default"]
        return jsonify(config)

    @app.post("/api/config/reset")
    def reset_config():
        store = app.config["STORE"]
        config = store.resetar_url()
        config["is_default"] = True
        return jsonify(config)

    @app.get("/api/favorites")
    def list_favorites():
        store = app.config["STORE"]
        return jsonify(sorted(store.carregar_favoritos()))

    @app.post("/api/favorites/toggle")
    def toggle_favorite():
        store = app.config["STORE"]
        payload = request.get_json(silent=True) or {}
        link = (payload.get("link") or "").strip()
        if not link:
            return jsonify({"erro": "Link não informado."}), 400
        favorito = store.alternar_favorito(link)
        return jsonify({"link": link, "favorito": favorito})

    @app.get("/api/scrape/status")
    def scrape_status():
        return jsonify(app.config["JOB_MANAGER"].status())

    @app.post("/api/scrape")
    def start_scrape():
        store = app.config["STORE"]
        job_manager = app.config["JOB_MANAGER"]
        status = job_manager.status()
        if status["state"] == "running":
            return jsonify(status), 409
        config = store.carregar_config()
        status = job_manager.start(config["url_atual"])
        return jsonify(status), 202

    return app


app = create_app()

if __name__ == "__main__":
    print("RadarSemFiador ativo em http://127.0.0.1:8000/")
    print("Use a interface para configurar a URL de busca e disparar o scraper.")
    app.run(host="127.0.0.1", port=8000, debug=False)
