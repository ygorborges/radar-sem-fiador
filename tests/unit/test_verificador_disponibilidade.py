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

from storage import Storage
from verificador_disponibilidade import _anuncio_ainda_disponivel


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
