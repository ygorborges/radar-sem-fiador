"""Testes do script de re-geocodificação com busca estruturada."""
import pytest

from corrigir_geocodificacao import corrigir_fonte
from storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


class TestCorrigirFonte:
    def test_regeocodifica_endereco_preciso_usando_a_rua(self, store, monkeypatch):
        chamadas = []

        def fake_geocodificar(endereco, cidade=None, estruturado=True):
            chamadas.append((endereco, cidade, estruturado))
            return (41.15, -8.61)

        import geolocalizacao
        monkeypatch.setattr(geolocalizacao, "geocodificar", fake_geocodificar)

        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "localizacao": {
                "lat": 41.999, "lon": -8.999, "preciso": True,
                "texto": "Praça da República, 183", "concelho": "Porto", "freguesia": "Bonfim",
            },
        }])

        alterados = corrigir_fonte("idealista", store)

        assert alterados == 1
        assert chamadas == [("Praça da República, 183", "Porto", True)]
        localizacao = store.carregar_resultados("idealista")[0]["localizacao"]
        assert (localizacao["lat"], localizacao["lon"]) == (41.15, -8.61)

    def test_regeocodifica_endereco_impreciso_usando_a_freguesia(self, store, monkeypatch):
        chamadas = []

        def fake_geocodificar(endereco, cidade=None, estruturado=True):
            chamadas.append((endereco, cidade, estruturado))
            return (41.15, -8.61)

        import geolocalizacao
        monkeypatch.setattr(geolocalizacao, "geocodificar", fake_geocodificar)

        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "localizacao": {
                "lat": 41.999, "lon": -8.999, "preciso": False,
                "texto": "Camões - Faria Guimarães", "concelho": "Porto",
                "freguesia": "Cedofeita, Santo Ildefonso, Sé, Miragaia, São Nicolau e Vitória",
            },
        }])

        corrigir_fonte("idealista", store)

        # Sem endereço preciso, pula direto pra freguesia com busca livre
        # (`estruturado=False` — o campo `street=` não reconhece um nome de
        # freguesia com vírgulas como rua).
        assert chamadas == [("Cedofeita, Santo Ildefonso, Sé, Miragaia, São Nicolau e Vitória", "Porto", False)]

    def test_sem_concelho_e_ignorado(self, store, monkeypatch):
        chamou = []
        import geolocalizacao
        monkeypatch.setattr(geolocalizacao, "geocodificar", lambda *a, **k: chamou.append(1))

        dados = [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.15, "lon": -8.61, "preciso": True, "texto": "x", "concelho": None, "freguesia": None},
        }]
        store.guardar_resultados("idealista", dados)

        assert corrigir_fonte("idealista", store) == 0
        assert not chamou
        assert store.carregar_resultados("idealista") == dados

    def test_coordenada_igual_nao_conta(self, store, monkeypatch):
        import geolocalizacao
        monkeypatch.setattr(geolocalizacao, "geocodificar", lambda endereco, cidade=None, estruturado=True: (41.15, -8.61))

        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.15, "lon": -8.61, "preciso": True, "texto": "x", "concelho": "Porto", "freguesia": "Bonfim"},
        }])

        assert corrigir_fonte("idealista", store) == 0

    def test_geocodificacao_sem_resultado_nenhum_e_ignorada(self, store, monkeypatch):
        import geolocalizacao
        monkeypatch.setattr(geolocalizacao, "geocodificar", lambda *a, **k: None)

        dados = [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.999, "lon": -8.999, "preciso": True, "texto": "x", "concelho": "Porto", "freguesia": "Bonfim"},
        }]
        store.guardar_resultados("idealista", dados)

        assert corrigir_fonte("idealista", store) == 0
        assert store.carregar_resultados("idealista") == dados

    def test_rua_nao_confirma_cidade_cai_para_freguesia_e_marca_aproximado(self, store, monkeypatch):
        # Regressão: a busca por rua não confirmou a cidade certa (achado
        # real: "Praça da República" resolvendo pra outra cidade) — manter a
        # coordenada antiga "precisa" seria continuar arriscando um endereço
        # nunca confirmado contra a cidade certa. Cai pra freguesia, que já
        # foi verificada via divisoes_administrativas.
        import geolocalizacao

        def fake_geocodificar(endereco, cidade=None, estruturado=True):
            if endereco == "Bonfim":
                return (41.15, -8.61)
            return None  # a rua nunca confirma "Porto"

        monkeypatch.setattr(geolocalizacao, "geocodificar", fake_geocodificar)

        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "localizacao": {
                "lat": 41.999, "lon": -8.999, "preciso": True,
                "texto": "Praça da República, 183", "concelho": "Porto", "freguesia": "Bonfim",
            },
        }])

        alterados = corrigir_fonte("idealista", store)

        assert alterados == 1
        localizacao = store.carregar_resultados("idealista")[0]["localizacao"]
        assert (localizacao["lat"], localizacao["lon"]) == (41.15, -8.61)
        assert localizacao["preciso"] is False

    def test_rua_e_freguesia_nao_confirmam_nada_mantem_o_valor_antigo(self, store, monkeypatch):
        import geolocalizacao
        monkeypatch.setattr(geolocalizacao, "geocodificar", lambda *a, **k: None)

        dados = [{
            "link": "https://a.pt/1",
            "localizacao": {
                "lat": 41.999, "lon": -8.999, "preciso": True,
                "texto": "Praça da República, 183", "concelho": "Porto", "freguesia": "Bonfim",
            },
        }]
        store.guardar_resultados("idealista", dados)

        assert corrigir_fonte("idealista", store) == 0
        assert store.carregar_resultados("idealista") == dados
