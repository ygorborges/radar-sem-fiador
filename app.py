"""Aplicação web do RadarArrendamento.

Processo único que serve a interface (`static/index.html`) e expõe uma API
para configurar a URL de busca de cada fonte (idealista, imovirtual, ...),
disparar os scrapers e favoritar anúncios. Basta rodar `python app.py`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from scrape_runner import ScrapeJobManager, VerificacaoJobManager, default_check_managers, default_job_managers
from storage import FONTES, Storage, default_storage

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def create_app(
    job_managers: Optional[dict[str, ScrapeJobManager]] = None,
    check_managers: Optional[dict[str, VerificacaoJobManager]] = None,
    store: Optional[Storage] = None,
) -> Flask:
    """Cria a aplicação Flask. Aceita `job_managers`/`check_managers`/`store` para testes isolados."""
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.config["JOB_MANAGERS"] = job_managers or default_job_managers
    app.config["CHECK_MANAGERS"] = check_managers or default_check_managers
    app.config["STORE"] = store or default_storage

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/results")
    def get_results():
        store = app.config["STORE"]
        resultados = store.carregar_resultados_todas_fontes()
        favoritos = store.carregar_favoritos()
        ocultos = store.carregar_ocultos()
        for item in resultados:
            item["favorito"] = item.get("link") in favoritos
            item["oculto"] = item.get("link") in ocultos
        return jsonify(resultados)

    @app.get("/api/config")
    def get_config():
        store = app.config["STORE"]
        config = store.carregar_config()
        for fonte, dados in config.items():
            dados["label"] = FONTES[fonte]["label"]
            dados["is_default"] = dados["url_atual"] == dados["url_default"]
        return jsonify(config)

    @app.post("/api/config/<fonte>")
    def update_config(fonte: str):
        if fonte not in FONTES:
            return jsonify({"erro": f"Fonte desconhecida: {fonte}"}), 404
        store = app.config["STORE"]
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        if not url:
            return jsonify({"erro": "A URL não pode estar vazia."}), 400
        dominio = FONTES[fonte]["dominio"]
        if not url.startswith(dominio):
            return jsonify({"erro": f"A URL deve ser uma busca do {FONTES[fonte]['label']} ({dominio})."}), 400
        config = store.guardar_url_atual(fonte, url)
        config["label"] = FONTES[fonte]["label"]
        config["is_default"] = config["url_atual"] == config["url_default"]
        return jsonify(config)

    @app.post("/api/config/<fonte>/reset")
    def reset_config(fonte: str):
        if fonte not in FONTES:
            return jsonify({"erro": f"Fonte desconhecida: {fonte}"}), 404
        store = app.config["STORE"]
        config = store.resetar_url(fonte)
        config["label"] = FONTES[fonte]["label"]
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
        return jsonify({fonte: manager.status() for fonte, manager in app.config["JOB_MANAGERS"].items()})

    @app.post("/api/scrape/<fonte>")
    def start_scrape(fonte: str):
        job_manager = app.config["JOB_MANAGERS"].get(fonte)
        if job_manager is None:
            return jsonify({"erro": f"Fonte desconhecida: {fonte}"}), 404
        store = app.config["STORE"]
        status = job_manager.status()
        if status["state"] == "running":
            return jsonify(status), 409
        config = store.carregar_config()
        status = job_manager.start(config[fonte]["url_atual"])
        return jsonify(status), 202

    @app.get("/api/hidden")
    def list_hidden():
        store = app.config["STORE"]
        return jsonify(sorted(store.carregar_ocultos()))

    @app.post("/api/hidden/toggle")
    def toggle_hidden():
        store = app.config["STORE"]
        payload = request.get_json(silent=True) or {}
        link = (payload.get("link") or "").strip()
        if not link:
            return jsonify({"erro": "Link não informado."}), 400
        oculto = store.alternar_oculto(link)
        return jsonify({"link": link, "oculto": oculto})

    @app.get("/api/check/status")
    def check_status():
        return jsonify({fonte: manager.status() for fonte, manager in app.config["CHECK_MANAGERS"].items()})

    @app.post("/api/check/<fonte>")
    def start_check(fonte: str):
        check_manager = app.config["CHECK_MANAGERS"].get(fonte)
        if check_manager is None:
            return jsonify({"erro": f"Fonte desconhecida: {fonte}"}), 404
        status = check_manager.status()
        if status["state"] == "running":
            return jsonify(status), 409
        status = check_manager.start()
        return jsonify(status), 202

    return app


app = create_app()

if __name__ == "__main__":
    print("RadarArrendamento ativo em http://127.0.0.1:8000/")
    print("Use a interface para configurar a URL de busca e disparar os scrapers.")
    app.run(host="127.0.0.1", port=8000, debug=False)
