"""Testes do script de correção de concelho/freguesia dos anúncios já guardados."""
import pytest

from corrigir_concelhos import corrigir_fonte, corrigir_todas
from storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


class TestCorrigirFonte:
    def test_corrige_concelho_errado_derivado_do_addressregion(self, store):
        # Regressão real: um anúncio da Maia guardado com concelho "Porto"
        # (o distrito, extraído por engano do addressRegion do Imovirtual).
        store.guardar_resultados("imovirtual", [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.2, "lon": -8.6, "preciso": True, "texto": "x", "concelho": "Porto", "freguesia": "Cidade da Maia"},
        }])

        alterados = corrigir_fonte("imovirtual", store)

        assert alterados == 1
        resultado = store.carregar_resultados("imovirtual")[0]
        assert resultado["localizacao"]["concelho"] == "Maia"

    def test_canonicaliza_freguesia_em_formato_diferente(self, store):
        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "localizacao": {
                "lat": 41.15, "lon": -8.6, "preciso": True, "texto": "x",
                "concelho": "Cedofeita - Santo Ildefonso - Sé - Miragaia - São Nicolau - Vitória",
                "freguesia": "Cedofeita - Santo Ildefonso - Sé - Miragaia - São Nicolau - Vitória",
            },
        }])

        alterados = corrigir_fonte("idealista", store)

        assert alterados == 1
        localizacao = store.carregar_resultados("idealista")[0]["localizacao"]
        assert localizacao["concelho"] == "Porto"
        assert localizacao["freguesia"] == "Cedofeita, Santo Ildefonso, Sé, Miragaia, São Nicolau e Vitória"

    def test_nao_conta_quando_ja_esta_correto(self, store):
        dados = [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.15, "lon": -8.6, "preciso": True, "texto": "x", "concelho": "Porto", "freguesia": "Bonfim"},
        }]
        store.guardar_resultados("idealista", dados)

        assert corrigir_fonte("idealista", store) == 0
        assert store.carregar_resultados("idealista") == dados

    def test_freguesia_nao_reconhecida_limpa_o_concelho_antigo(self, store):
        # "Camões - Faria Guimarães" é uma zona informal do idealista, sem
        # correspondência oficial — um concelho antigo (possivelmente
        # errado, herdado do texto bruto de antes desse módulo existir) não
        # deve persistir só porque não conseguimos confirmar um novo.
        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.15, "lon": -8.6, "preciso": True, "texto": "x", "concelho": "Porto", "freguesia": "Camões - Faria Guimarães"},
        }])

        alterados = corrigir_fonte("idealista", store)

        assert alterados == 1
        localizacao = store.carregar_resultados("idealista")[0]["localizacao"]
        assert localizacao["concelho"] is None
        assert localizacao["freguesia"] == "Camões - Faria Guimarães"

    def test_freguesia_nao_reconhecida_e_concelho_ja_none_nao_conta(self, store):
        dados = [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.15, "lon": -8.6, "preciso": True, "texto": "x", "concelho": None, "freguesia": "Camões - Faria Guimarães"},
        }]
        store.guardar_resultados("idealista", dados)

        assert corrigir_fonte("idealista", store) == 0
        assert store.carregar_resultados("idealista") == dados

    def test_nome_ambiguo_entre_concelhos_limpa_o_concelho_antigo(self, store):
        # "Paranhos" sozinho é ambíguo (Porto e Seia têm uma freguesia com
        # esse nome) — mesma lógica: não confirmado, não mantido. O
        # concelho antigo aqui ("Lisboa") não é nenhum dos dois candidatos,
        # então nem serve de dica pra desempatar (ver TestDesempatePorDicaDeCidade
        # em test_divisoes_administrativas.py para o caso em que desempata).
        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.15, "lon": -8.6, "preciso": True, "texto": "x", "concelho": "Lisboa", "freguesia": "Paranhos"},
        }])

        alterados = corrigir_fonte("idealista", store)

        assert alterados == 1
        assert store.carregar_resultados("idealista")[0]["localizacao"]["concelho"] is None

    def test_concelho_antigo_desempata_nome_ambiguo(self, store):
        # O concelho antigo do idealista era literalmente o último item bruto
        # da lista de localização (ex.: "Vila Nova de Gaia, Porto") — mesmo
        # não sendo um concelho "limpo", ainda serve pra desempatar uma
        # freguesia ambígua como "Oliveira do Douro" (Cinfães vs. Gaia).
        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.15, "lon": -8.6, "preciso": True, "texto": "x", "concelho": "Vila Nova de Gaia, Porto", "freguesia": "Oliveira do Douro"},
        }])

        alterados = corrigir_fonte("idealista", store)

        assert alterados == 1
        assert store.carregar_resultados("idealista")[0]["localizacao"]["concelho"] == "Vila Nova de Gaia"

    def test_sem_localizacao_e_ignorado(self, store):
        dados = [{"link": "https://a.pt/1"}]
        store.guardar_resultados("idealista", dados)
        assert corrigir_fonte("idealista", store) == 0
        assert store.carregar_resultados("idealista") == dados

    def test_sem_resultados_nao_faz_nada(self, store):
        assert corrigir_fonte("idealista", store) == 0


class TestCorrigirTodas:
    def test_corrige_cada_fonte_independentemente(self, store):
        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "localizacao": {"lat": 41.15, "lon": -8.6, "preciso": True, "texto": "x", "concelho": "Porto", "freguesia": "Aldoar"},
        }])
        store.guardar_resultados("imovirtual", [{
            "link": "https://b.pt/1",
            "localizacao": {"lat": 41.2, "lon": -8.6, "preciso": True, "texto": "y", "concelho": "Porto", "freguesia": "Fânzeres e São Pedro da Cova"},
        }])

        alterados = corrigir_todas(store)

        assert alterados["idealista"] == 1
        assert alterados["imovirtual"] == 1
        assert store.carregar_resultados("imovirtual")[0]["localizacao"]["concelho"] == "Gondomar"
