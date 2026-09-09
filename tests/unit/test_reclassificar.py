"""Testes do script de reclassificação de anúncios já guardados."""
import pytest

from reclassificar import reclassificar_fonte, reclassificar_todas
from storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


class TestReclassificarFonte:
    def test_atualiza_status_quando_a_classificacao_muda(self, store):
        store.guardar_resultados("idealista", [
            {
                "link": "https://a.pt/1",
                "descricao": "Na ausência de Fiador terá de ser analisado.",
                "status": "EXIGE FIADOR",
                "trecho_status": "fiador",
                "passou_filtro": True,
            },
        ])

        alterados = reclassificar_fonte("idealista", store)

        assert alterados == 1
        resultado = store.carregar_resultados("idealista")[0]
        assert resultado["status"] == "CONFIRMADO (Explícito/Flexível)"

    def test_nao_conta_nem_reescreve_quando_status_nao_muda(self, store):
        dados = [{
            "link": "https://a.pt/1",
            "descricao": "Apartamento sem fiador, aceita-se caução reforçada.",
            "status": "CONFIRMADO (Explícito/Flexível)",
            "trecho_status": "sem fiador",
            "passou_filtro": True,
        }]
        store.guardar_resultados("idealista", dados)

        alterados = reclassificar_fonte("idealista", store)

        assert alterados == 0
        assert store.carregar_resultados("idealista") == dados

    def test_sem_resultados_nao_faz_nada(self, store):
        assert reclassificar_fonte("idealista", store) == 0

    def test_nao_rebaixa_status_quando_descricao_truncada_perdeu_a_mencao(self, store):
        # Regressão: anúncios salvos antes da descrição completa existir
        # mantêm só um trecho de ~250 caracteres. Se esse trecho não
        # contiver mais "fiador" (foi cortado), reclassificar não pode virar
        # "SEM MENÇÃO" — isso apagaria uma classificação que era correta na
        # época (feita sobre o texto completo, só truncado depois).
        item_truncado = {
            "link": "https://a.pt/1",
            "descricao": "Apartamento T2 bem localizado, junto ao metro, com garagem incluída no preço.",
            "status": "EXIGE FIADOR",
            "trecho_status": "fiador obrigatório (texto original, hoje perdido pela truncagem)",
            "passou_filtro": True,
        }
        store.guardar_resultados("idealista", [item_truncado])

        alterados = reclassificar_fonte("idealista", store)

        assert alterados == 0
        assert store.carregar_resultados("idealista")[0] == item_truncado

    def test_reclassifica_normalmente_quando_status_antigo_nao_confirmava_fiador(self, store):
        # ERRO_TEXTO_VAZIO/BLOQUEADO_POR_ANTI_BOT nunca confirmaram a
        # presença da palavra "fiador" (a página só falhou em carregar) —
        # não há risco de truncagem escondida nesses casos, então a
        # proteção não deve impedir a correção.
        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "descricao": "Apartamento T2 sem qualquer menção a esse assunto no texto.",
            "status": "ERRO_TEXTO_VAZIO",
        }])

        alterados = reclassificar_fonte("idealista", store)

        assert alterados == 1
        assert store.carregar_resultados("idealista")[0]["status"] == "SEM MENÇÃO (Não cita fiador)"


class TestReclassificarTodas:
    def test_reclassifica_cada_fonte_independentemente(self, store):
        store.guardar_resultados("idealista", [{
            "link": "https://a.pt/1",
            "descricao": "Na ausência de fiador, aceitamos negociar.",
            "status": "EXIGE FIADOR",
        }])
        store.guardar_resultados("imovirtual", [{
            "link": "https://b.pt/1",
            "descricao": "Apartamento com vista para o rio.",
            "status": "ERRO_TEXTO_VAZIO",
        }])

        alterados = reclassificar_todas(store)

        assert alterados["idealista"] == 1
        assert alterados["imovirtual"] == 1
        assert store.carregar_resultados("imovirtual")[0]["status"] == "SEM MENÇÃO (Não cita fiador)"
