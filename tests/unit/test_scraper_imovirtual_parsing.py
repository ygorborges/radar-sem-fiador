"""Testes das funções puras do scraper do Imovirtual (sem Playwright)."""
import scraper_imovirtual as si


class TestConstruirUrlPagina:
    def test_pagina_1_nao_adiciona_parametro_page(self):
        url = "https://www.imovirtual.com/pt/resultados/arrendar/apartamento/porto/porto?priceMax=1000"
        assert si.construir_url_pagina(url, 1) == url

    def test_pagina_1_remove_parametro_page_existente(self):
        url = "https://www.imovirtual.com/pt/resultados?priceMax=1000&page=3"
        resultado = si.construir_url_pagina(url, 1)
        assert "page=" not in resultado
        assert "priceMax=1000" in resultado

    def test_pagina_maior_que_1_adiciona_parametro(self):
        url = "https://www.imovirtual.com/pt/resultados?priceMax=1000"
        resultado = si.construir_url_pagina(url, 3)
        assert "page=3" in resultado
        assert "priceMax=1000" in resultado

    def test_pagina_maior_que_1_substitui_parametro_existente(self):
        url = "https://www.imovirtual.com/pt/resultados?priceMax=1000&page=2"
        resultado = si.construir_url_pagina(url, 5)
        assert "page=5" in resultado
        assert "page=2" not in resultado


class TestExtrairNumeroPaginaDoTitulo:
    def test_sem_prefixo_e_pagina_1(self):
        titulo = "Casas e apartamentos para arrendar: Porto, Porto | Imovirtual.com"
        assert si.extrair_numero_pagina_do_titulo(titulo) == 1

    def test_le_numero_do_prefixo(self):
        titulo = "Página 4 - Casas e apartamentos para arrendar: Porto, Porto | Imovirtual.com"
        assert si.extrair_numero_pagina_do_titulo(titulo) == 4

    def test_titulo_vazio_e_pagina_1(self):
        assert si.extrair_numero_pagina_do_titulo("") == 1
        assert si.extrair_numero_pagina_do_titulo(None) == 1


class TestNormalizarHrefAnuncio:
    def test_remove_prefixo_hpr(self):
        # Achado real: essa variante devolve 404 quando visitada diretamente.
        href = "/hpr/pt/anuncio/apartamento-t1-rua-5-de-outubro-casa-da-musica-ID15LUN"
        assert si.normalizar_href_anuncio(href) == "/pt/anuncio/apartamento-t1-rua-5-de-outubro-casa-da-musica-ID15LUN"

    def test_href_normal_fica_inalterado(self):
        href = "/pt/anuncio/apartamento-t1-rua-5-de-outubro-casa-da-musica-ID15LUN"
        assert si.normalizar_href_anuncio(href) == href

    def test_variantes_do_mesmo_anuncio_normalizam_para_o_mesmo_link(self):
        normal = si.normalizar_href_anuncio("/pt/anuncio/alugo-t1-areosa-porto-ID1iPab")
        promovido = si.normalizar_href_anuncio("/hpr/pt/anuncio/alugo-t1-areosa-porto-ID1iPab")
        assert normal == promovido


class TestExtrairDataAtualizacao:
    def test_extrai_data_com_ano_incluido(self):
        # Ao contrário do idealista, o Imovirtual sempre inclui o ano — sem ambiguidade.
        assert si.extrair_data_atualizacao("Última atualização: 8.09.2026") == "2026-09-08"

    def test_extrai_data_com_dia_e_mes_de_dois_digitos(self):
        assert si.extrair_data_atualizacao("Última atualização: 14.12.2025") == "2025-12-14"

    def test_texto_sem_padrao_retorna_none(self):
        assert si.extrair_data_atualizacao("Nenhuma informação de data aqui.") is None

    def test_texto_vazio_retorna_none(self):
        assert si.extrair_data_atualizacao("") is None
        assert si.extrair_data_atualizacao(None) is None

    def test_data_invalida_retorna_none(self):
        assert si.extrair_data_atualizacao("Última atualização: 32.13.2026") is None


class TestExtrairDoJsonLd:
    def _no_produto(self, **overrides):
        base = {
            "@type": ["Product", "Apartment"],
            "name": "Apartamento T1 Rua 5 de Outubro - Casa da Música",
            "description": "<p>Apartamento T1, cozinha equipada. Exige-se fiadores idóneos/caução.</p>",
            "offers": {"@type": "Offer", "priceCurrency": "EUR", "price": 900},
            "additionalProperty": [
                {"@type": "PropertyValue", "name": "Tipologia", "value": "T1"},
                {"@type": "PropertyValue", "name": "Tipo de anunciante", "value": "particular"},
            ],
        }
        base.update(overrides)
        return base

    def _documento(self, node):
        return {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, node]}

    def test_extrai_campos_principais(self):
        resultado = si._extrair_do_json_ld(self._documento(self._no_produto()))
        assert resultado is not None
        assert resultado["titulo"] == "Apartamento T1 Rua 5 de Outubro - Casa da Música"
        assert "fiadores" in resultado["descricao"].lower()
        assert "<p>" not in resultado["descricao"]
        assert resultado["preco"] == "900 €/mês"
        assert resultado["tipologia"] == "T1"
        assert resultado["tipo_anunciante"] == "Particular"

    def test_tipo_anunciante_profissional_normalizado(self):
        node = self._no_produto(additionalProperty=[
            {"@type": "PropertyValue", "name": "Tipologia", "value": "T2"},
            {"@type": "PropertyValue", "name": "Tipo de anunciante", "value": "profissional"},
        ])
        resultado = si._extrair_do_json_ld(self._documento(node))
        assert resultado["tipo_anunciante"] == "Profissional"

    def test_sem_graph_retorna_none(self):
        assert si._extrair_do_json_ld({"@context": "https://schema.org"}) is None

    def test_sem_node_product_retorna_none(self):
        documento = {"@graph": [{"@type": "WebPage", "name": "Só uma página qualquer"}]}
        assert si._extrair_do_json_ld(documento) is None

    def test_preco_ausente_vira_na(self):
        node = self._no_produto(offers={"@type": "Offer"})
        resultado = si._extrair_do_json_ld(self._documento(node))
        assert resultado["preco"] == "N/A"

    def test_sem_titulo_ou_descricao_nao_e_aceito(self):
        node = self._no_produto(description="")
        assert si._extrair_do_json_ld(self._documento(node)) is None
