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


def _candidato(lat, lon, cidade):
    return {"lat": str(lat), "lon": str(lon), "address": {"city": cidade}}


class TestGeocodificarComCidade:
    def test_com_cidade_usa_busca_estruturada(self, monkeypatch):
        urls_chamadas = []

        def _fake(request, timeout=10):
            urls_chamadas.append(request.full_url)
            return _RespostaFalsa(json.dumps([_candidato(41.15, -8.61, "Porto")]).encode("utf-8"))

        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _fake)

        resultado = geolocalizacao.geocodificar("Praça da República, 183", cidade="Porto")
        assert resultado == (41.15, -8.61)
        assert len(urls_chamadas) == 1
        assert "street=" in urls_chamadas[0]
        assert "city=Porto" in urls_chamadas[0]
        assert "q=" not in urls_chamadas[0]

    def test_sem_cidade_usa_busca_livre(self, monkeypatch):
        urls_chamadas = []

        def _fake(request, timeout=10):
            urls_chamadas.append(request.full_url)
            return _RespostaFalsa(json.dumps([{"lat": "41.15", "lon": "-8.61"}]).encode("utf-8"))

        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _fake)

        geolocalizacao.geocodificar("Rua X, Porto, Portugal")
        assert "q=" in urls_chamadas[0]
        assert "street=" not in urls_chamadas[0]

    def test_com_cidade_e_estruturado_false_usa_busca_livre_com_verificacao(self, monkeypatch):
        # Regressão: o campo `street=` da Nominatim não reconhece um nome de
        # freguesia com vírgulas ("Cedofeita, Santo Ildefonso, Sé, Miragaia,
        # São Nicolau e Vitória") como rua — devolvia zero candidatos. Busca
        # livre (`q=`) funciona bem pra nome de área/freguesia, mas ainda
        # precisa confirmar a cidade certa (mesma verificação de sempre).
        urls_chamadas = []

        def _fake(request, timeout=10):
            urls_chamadas.append(request.full_url)
            return _RespostaFalsa(json.dumps([_candidato(41.15, -8.61, "Porto")]).encode("utf-8"))

        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _fake)

        resultado = geolocalizacao.geocodificar("Cedofeita, Santo Ildefonso e Vitória", cidade="Porto", estruturado=False)
        assert resultado == (41.15, -8.61)
        assert "q=" in urls_chamadas[0]
        assert "street=" not in urls_chamadas[0]

    def test_com_cidade_e_estruturado_false_ainda_rejeita_cidade_errada(self, monkeypatch):
        monkeypatch.setattr(
            geolocalizacao.urllib.request, "urlopen",
            _urlopen_com_resultado([_candidato(41.99, -8.99, "Outra Cidade")]),
        )
        assert geolocalizacao.geocodificar("Alguma Freguesia", cidade="Porto", estruturado=False) is None

    def test_rejeita_candidato_de_cidade_errada(self, monkeypatch):
        # Regressão real: pedindo "Praça da República" + city=Porto, a
        # Nominatim devolvia em primeiro lugar uma "Praça da República" na
        # Póvoa de Varzim (importância maior no OSM, apesar da cidade
        # errada) — o parâmetro `city` sozinho não filtra com rigor, ele
        # também compara com o distrito ("county"), que é o mesmo pra
        # Porto/Póvoa de Varzim/etc. Um único candidato com cidade errada,
        # sem nenhum outro, deve virar `None` — não a coordenada errada.
        monkeypatch.setattr(
            geolocalizacao.urllib.request, "urlopen",
            _urlopen_com_resultado([_candidato(41.3786808, -8.761967, "Póvoa de Varzim")]),
        )
        assert geolocalizacao.geocodificar("Praça da República", cidade="Porto") is None

    def test_escolhe_o_candidato_com_a_cidade_certa_entre_varios(self, monkeypatch):
        candidatos = [
            _candidato(41.3786808, -8.761967, "Póvoa de Varzim"),
            _candidato(41.1544033, -8.6126717, "Porto"),
            _candidato(41.2761313, -8.3767927, "Paços de Ferreira"),
        ]
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _urlopen_com_resultado(candidatos))
        assert geolocalizacao.geocodificar("Praça da República", cidade="Porto") == (41.1544033, -8.6126717)

    def test_aceita_cidade_em_town_ou_municipality(self, monkeypatch):
        candidato = {"lat": "41.15", "lon": "-8.61", "address": {"town": "Porto"}}
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _urlopen_com_resultado([candidato]))
        assert geolocalizacao.geocodificar("Rua X", cidade="Porto") == (41.15, -8.61)

    def test_comparacao_de_cidade_ignora_acentos_e_maiusculas(self, monkeypatch):
        candidato = _candidato(41.15, -8.61, "PORTO")
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _urlopen_com_resultado([candidato]))
        assert geolocalizacao.geocodificar("Rua X", cidade="porto") == (41.15, -8.61)


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

    def test_cache_com_cidade_usa_chave_diferente_da_busca_livre(self, monkeypatch, store):
        chamadas = []

        def _fake(request, timeout=10):
            chamadas.append(1)
            return _RespostaFalsa(json.dumps([_candidato(41.15, -8.61, "Porto")]).encode("utf-8"))

        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _fake)

        geolocalizacao.geocodificar_com_cache("Rua X", store, cidade="Porto")
        geolocalizacao.geocodificar_com_cache("Rua X", store)  # busca livre, sem cidade

        assert len(chamadas) == 2
        assert set(store.carregar_cache_geocodificacao().keys()) == {"Rua X, Porto", "Rua X"}

    def test_cache_distingue_estruturado_de_livre_para_mesmo_texto_e_cidade(self, monkeypatch, store):
        chamadas = []

        def _fake(request, timeout=10):
            chamadas.append(1)
            return _RespostaFalsa(json.dumps([_candidato(41.15, -8.61, "Porto")]).encode("utf-8"))

        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _fake)

        geolocalizacao.geocodificar_com_cache("X", store, cidade="Porto", estruturado=True)
        geolocalizacao.geocodificar_com_cache("X", store, cidade="Porto", estruturado=False)

        assert len(chamadas) == 2
        assert set(store.carregar_cache_geocodificacao().keys()) == {"X, Porto", "X, Porto (livre)"}

    def test_endereco_nao_encontrado_e_cacheado_como_none(self, monkeypatch, store):
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", _urlopen_com_resultado([]))

        assert geolocalizacao.geocodificar_com_cache("Endereço fantasma", store) is None
        assert store.carregar_cache_geocodificacao() == {"Endereço fantasma": None}

        # Uma segunda chamada não deve tentar de novo (continua sem bater na API).
        chamou = []
        monkeypatch.setattr(geolocalizacao.urllib.request, "urlopen", lambda *a, **k: chamou.append(1))
        assert geolocalizacao.geocodificar_com_cache("Endereço fantasma", store) is None
        assert not chamou
