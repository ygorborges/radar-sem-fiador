"""Testes da geocodificação (Nominatim), sem bater na rede de verdade.

`geocodificar` faz uma chamada HTTP real via `urllib`; aqui `urlopen` é
substituído por um dublê que devolve uma resposta fabricada, e o limitador de
taxa é zerado antes de cada teste para não introduzir esperas reais de 1s.
"""
import json
import io

import pytest

import geolocalizacao
from storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


@pytest.fixture(autouse=True)
def sem_limite_de_taxa(monkeypatch):
    # Evita que os testes esperem de verdade o intervalo mínimo entre pedidos.
    monkeypatch.setattr(geolocalizacao, "_respeitar_limite_de_taxa", lambda: None)


class _RespostaFalsa:
    def __init__(self, corpo: bytes):
        self._buffer = io.BytesIO(corpo)

    def read(self):
        return self._buffer.read()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _urlopen_com_resultado(dados_json):
    def _fake(request, timeout=10):
        return _RespostaFalsa(json.dumps(dados_json).encode("utf-8"))
    return _fake


class TestGeocodificar:
    def test_endereco_vazio_nao_chama_a_api(self, monkeypatch):
        chamou = []
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", lambda *a, **k: chamou.append(1))
        assert geolocalizacao.geocodificar("") is None
        assert geolocalizacao.geocodificar(None) is None
        assert not chamou

    def test_resultado_encontrado_devolve_lat_lon(self, monkeypatch):
        monkeypatch.setattr(
            geolocalizacao.urllib.request, "urlopen",
            _urlopen_com_resultado([{"lat": "41.15", "lon": "-8.61"}]),
        )
        assert geolocalizacao.geocodificar("Rua X, Porto, Portugal") == (41.15, -8.61)

    def test_sem_resultados_devolve_none(self, monkeypatch):
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _urlopen_com_resultado([]))
        assert geolocalizacao.geocodificar("Endereço que não existe") is None

    def test_falha_de_rede_devolve_none(self, monkeypatch):
        def _fake(request, timeout=10):
            raise OSError("falha simulada de rede")
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _fake)
        assert geolocalizacao.geocodificar("Rua X, Porto, Portugal") is None

    def test_resposta_malformada_devolve_none(self, monkeypatch):
        monkeypatch.setattr(
            geolocalizacao.urllib.request, "urlopen",
            _urlopen_com_resultado([{"algo": "inesperado"}]),
        )
        assert geolocalizacao.geocodificar("Rua X, Porto, Portugal") is None


class TestGeocodificarComCache:
    def test_primeira_chamada_consulta_a_api_e_guarda_no_cache(self, monkeypatch, store):
        chamadas = []

        def _fake(request, timeout=10):
            chamadas.append(1)
            return _RespostaFalsa(json.dumps([{"lat": "41.15", "lon": "-8.61"}]).encode("utf-8"))

        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _fake)

        resultado = geolocalizacao.geocodificar_com_cache("Rua X, Porto, Portugal", store)
        assert resultado == (41.15, -8.61)
        assert len(chamadas) == 1
        assert store.carregar_cache_geocodificacao() == {"Rua X, Porto, Portugal": [41.15, -8.61]}

    def test_segunda_chamada_usa_o_cache_sem_bater_na_api(self, monkeypatch, store):
        store.guardar_cache_geocodificacao({"Rua X, Porto, Portugal": [41.15, -8.61]})

        chamou = []
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", lambda *a, **k: chamou.append(1))

        resultado = geolocalizacao.geocodificar_com_cache("Rua X, Porto, Portugal", store)
        assert resultado == (41.15, -8.61)
        assert not chamou

    def test_endereco_nao_encontrado_e_cacheado_como_none(self, monkeypatch, store):
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _urlopen_com_resultado([]))

        assert geolocalizacao.geocodificar_com_cache("Endereço fantasma", store) is None
        assert store.carregar_cache_geocodificacao() == {"Endereço fantasma": None}

        # Uma segunda chamada não deve tentar de novo (continua sem bater na API).
        chamou = []
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", lambda *a, **k: chamou.append(1))
        assert geolocalizacao.geocodificar_com_cache("Endereço fantasma", store) is None
        assert not chamou
