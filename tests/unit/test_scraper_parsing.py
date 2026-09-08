"""Testes das funções específicas do scraper do idealista (sem Playwright).

As funções de classificação de fiador, comuns a todas as fontes, têm os
seus testes em `test_classificacao.py`.
"""
from datetime import date

import scraper


class TestExtrairDataAtualizacao:
    def test_extrai_data_dentro_do_ano_corrente(self):
        hoje = date(2026, 9, 8)
        resultado = scraper.extrair_data_atualizacao("Anúncio atualizado no dia 14 de Agosto", hoje=hoje)
        assert resultado == "2026-08-14"

    def test_data_futura_assume_ano_anterior(self):
        # Em janeiro, um "atualizado no dia 20 de Dezembro" só pode ser do ano passado.
        hoje = date(2026, 1, 10)
        resultado = scraper.extrair_data_atualizacao("Anúncio atualizado no dia 20 de Dezembro", hoje=hoje)
        assert resultado == "2025-12-20"

    def test_texto_sem_padrao_retorna_none(self):
        assert scraper.extrair_data_atualizacao("Nenhuma informação de data aqui.") is None

    def test_texto_vazio_retorna_none(self):
        assert scraper.extrair_data_atualizacao("") is None
        assert scraper.extrair_data_atualizacao(None) is None

    def test_mes_invalido_retorna_none(self):
        assert scraper.extrair_data_atualizacao("Anúncio atualizado no dia 14 de Nãomes") is None
