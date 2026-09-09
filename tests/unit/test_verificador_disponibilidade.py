"""Testes do verificador de disponibilidade (sem Playwright real).

Segue o mesmo padrão de `test_scraper_playwright_helpers.py`: um dublê (fake)
mínimo de `page` no lugar de um browser real, rodando a coroutine com
`asyncio.run`. A orquestração completa (`verificar_disponibilidade`, que abre
um browser de verdade via Playwright) não é testada aqui — assim como
`raspar_idealista_porto`/`raspar_imovirtual` também não são — só a função
pura que decide, a partir de uma resposta/texto de página, se o anúncio
ainda está disponível.
"""
import asyncio

import pytest

import scraper
import scraper_imovirtual
from storage import Storage
from verificador_disponibilidade import (
    _anuncio_ainda_disponivel,
    _extrair_descricao_atual,
    _localizacao_incompleta,
)


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


class _RespostaFalsa:
    def __init__(self, status: int):
        self.status = status


class _PaginaFalsa:
    def __init__(self, status: int = 200, texto: str = "", falha_no_goto: bool = False):
        self._status = status
        self._texto = texto
        self._falha_no_goto = falha_no_goto

    async def goto(self, url, wait_until=None, timeout=None):
        if self._falha_no_goto:
            raise TimeoutError("timeout simulado")
        return _RespostaFalsa(self._status)

    async def evaluate(self, script):
        return self._texto


class TestAnuncioAindaDisponivel:
    def test_status_404_e_indisponivel(self, store):
        page = _PaginaFalsa(status=404)
        assert asyncio.run(_anuncio_ainda_disponivel(page, "https://a.pt/1", store)) is False

    def test_texto_normal_continua_disponivel(self, store):
        page = _PaginaFalsa(status=200, texto="Apartamento T2 disponível para arrendar, sem fiador.")
        assert asyncio.run(_anuncio_ainda_disponivel(page, "https://a.pt/1", store)) is True

    def test_texto_de_anuncio_removido_e_indisponivel(self, store):
        page = _PaginaFalsa(status=200, texto="Este anúncio já não está disponível.")
        assert asyncio.run(_anuncio_ainda_disponivel(page, "https://a.pt/1", store)) is False

    def test_falha_de_rede_mantem_como_disponivel(self, store):
        # Uma instabilidade passageira não pode fazer um anúncio real
        # desaparecer da listagem — só uma confirmação positiva marca como
        # indisponível.
        page = _PaginaFalsa(falha_no_goto=True)
        assert asyncio.run(_anuncio_ainda_disponivel(page, "https://a.pt/1", store)) is True


class TestLocalizacaoIncompleta:
    def test_sem_localizacao_e_incompleta(self):
        assert _localizacao_incompleta({"link": "https://a.pt/1"}) is True

    def test_localizacao_none_e_incompleta(self):
        assert _localizacao_incompleta({"link": "https://a.pt/1", "localizacao": None}) is True

    def test_localizacao_sem_concelho_e_incompleta(self):
        # Formato salvo antes do campo `concelho`/`freguesia` existir.
        item = {"localizacao": {"lat": 41.15, "lon": -8.61, "preciso": True, "texto": "Rua X"}}
        assert _localizacao_incompleta(item) is True

    def test_localizacao_completa_nao_e_incompleta(self):
        item = {"localizacao": {"lat": 41.15, "lon": -8.61, "preciso": True, "texto": "Rua X", "concelho": "Porto", "freguesia": "Bonfim"}}
        assert _localizacao_incompleta(item) is False


class TestExtrairDescricaoAtual:
    """`_extrair_descricao_atual` só normaliza o formato de retorno de cada
    scraper (tupla no idealista, dict no Imovirtual) — a extração em si já é
    testada nos próprios scrapers, então aqui os `extrair_dados_detalhe`
    reais são substituídos por dublês.
    """

    def test_idealista_desempacota_a_tupla(self, monkeypatch):
        async def fake_extrair(page):
            return "Título", "800 €/mês", "Descrição completa de teste."

        monkeypatch.setattr(scraper, "extrair_dados_detalhe", fake_extrair)
        resultado = asyncio.run(_extrair_descricao_atual("idealista", page=None))
        assert resultado == "Descrição completa de teste."

    def test_imovirtual_le_a_chave_do_dict(self, monkeypatch):
        async def fake_extrair(page):
            return {"titulo": "Título", "preco": "800 €/mês", "descricao": "Descrição completa de teste."}

        monkeypatch.setattr(scraper_imovirtual, "extrair_dados_detalhe", fake_extrair)
        resultado = asyncio.run(_extrair_descricao_atual("imovirtual", page=None))
        assert resultado == "Descrição completa de teste."

    def test_erro_na_extracao_devolve_none(self, monkeypatch):
        async def fake_extrair_com_erro(page):
            raise RuntimeError("falha simulada")

        monkeypatch.setattr(scraper, "extrair_dados_detalhe", fake_extrair_com_erro)
        assert asyncio.run(_extrair_descricao_atual("idealista", page=None)) is None

    def test_fonte_desconhecida_devolve_none(self):
        assert asyncio.run(_extrair_descricao_atual("olx", page=None)) is None
