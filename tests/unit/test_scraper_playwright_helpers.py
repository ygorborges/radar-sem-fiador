"""Testes dos extratores assíncronos que dependem de uma `page` do Playwright.

Usa um dublê (fake) mínimo em vez de abrir um browser real, e roda a
coroutine com `asyncio.run` para não depender do plugin pytest-asyncio.
"""
import asyncio

import scraper


class _ElementoFalso:
    def __init__(self, texto: str):
        self._texto = texto

    async def inner_text(self) -> str:
        return self._texto


class _PaginaFalsa:
    """Simula `page.wait_for_selector`: retorna o elemento se o seletor
    esperado for consultado, ou levanta (como o Playwright faz ao expirar
    o timeout) caso contrário."""

    def __init__(self, seletor_disponivel: str | None, texto: str = ""):
        self._seletor_disponivel = seletor_disponivel
        self._texto = texto

    async def wait_for_selector(self, seletor: str, timeout: int = 5000):
        if seletor == self._seletor_disponivel:
            return _ElementoFalso(self._texto)
        raise TimeoutError(f"seletor {seletor!r} não encontrado (simulado)")


class TestExtrairTipoAnunciantePagina:
    def test_le_particular_do_elemento_professional_name(self):
        page = _PaginaFalsa(".professional-name", "Particular\nSimão Macedo")
        resultado = asyncio.run(scraper.extrair_tipo_anunciante_pagina(page))
        assert resultado == "Particular"

    def test_le_profissional_do_elemento_professional_name(self):
        page = _PaginaFalsa(".professional-name", "Profissional\nSAIMÓVEIS SOC. MEDIAÇÃO IMOBILIÁRIA")
        resultado = asyncio.run(scraper.extrair_tipo_anunciante_pagina(page))
        assert resultado == "Profissional"

    def test_elemento_ausente_retorna_none_para_cair_no_fallback(self):
        page = _PaginaFalsa(seletor_disponivel=None)
        resultado = asyncio.run(scraper.extrair_tipo_anunciante_pagina(page))
        assert resultado is None

    def test_texto_inesperado_no_elemento_retorna_none(self):
        page = _PaginaFalsa(".professional-name", "Algo inesperado")
        resultado = asyncio.run(scraper.extrair_tipo_anunciante_pagina(page))
        assert resultado is None
