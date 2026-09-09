"""Testes da camada de persistência (Storage), isolados em pasta temporária."""
import pytest

from storage import FONTES, Storage, URL_BASE_DEFAULT_IDEALISTA, URL_BASE_DEFAULT_IMOVIRTUAL


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


class TestHistorico:
    """Histórico é único e partilhado entre fontes (links já são globalmente únicos)."""

    def test_historico_vazio_quando_nao_existe(self, store):
        assert store.carregar_historico() == set()

    def test_guarda_e_recarrega_historico(self, store):
        store.guardar_historico({"https://a.pt/1", "https://imovirtual.com/2"})
        assert store.carregar_historico() == {"https://a.pt/1", "https://imovirtual.com/2"}


class TestResultados:
    def test_resultados_vazios_quando_nao_existe(self, store):
        assert store.carregar_resultados("idealista") == []

    def test_fonte_desconhecida_levanta_erro(self, store):
        with pytest.raises(ValueError):
            store.carregar_resultados("olx")

    def test_guarda_e_recarrega_resultados(self, store):
        dados = [{"titulo": "Apto T2", "link": "https://a.pt/1"}]
        store.guardar_resultados("idealista", dados)
        assert store.carregar_resultados("idealista") == dados

    def test_fontes_diferentes_ficam_em_ficheiros_separados(self, store):
        store.guardar_resultados("idealista", [{"titulo": "Do idealista", "link": "https://a.pt/1"}])
        store.guardar_resultados("imovirtual", [{"titulo": "Do imovirtual", "link": "https://b.pt/1"}])

        assert store.carregar_resultados("idealista") == [{"titulo": "Do idealista", "link": "https://a.pt/1"}]
        assert store.carregar_resultados("imovirtual") == [{"titulo": "Do imovirtual", "link": "https://b.pt/1"}]

    def test_carregar_resultados_todas_fontes_marca_cada_item_com_a_fonte(self, store):
        store.guardar_resultados("idealista", [{"titulo": "Do idealista", "link": "https://a.pt/1"}])
        store.guardar_resultados("imovirtual", [{"titulo": "Do imovirtual", "link": "https://b.pt/1"}])

        todos = store.carregar_resultados_todas_fontes()
        por_link = {item["link"]: item["fonte"] for item in todos}
        assert por_link == {"https://a.pt/1": "idealista", "https://b.pt/1": "imovirtual"}

    def test_atualizar_resultados_preserva_achados_de_execucoes_anteriores(self, store):
        store.guardar_resultados("idealista", [
            {"titulo": "Anúncio antigo", "link": "https://a.pt/1", "status": "CONFIRMADO"},
        ])

        resultado = store.atualizar_resultados("idealista", [
            {"titulo": "Anúncio novo", "link": "https://a.pt/2", "status": "EXIGE FIADOR"},
        ])

        links = {item["link"] for item in resultado}
        assert links == {"https://a.pt/1", "https://a.pt/2"}
        # A varredura seguinte não revisita ".../1" (já está no histórico), mas
        # o anúncio encontrado antes não pode desaparecer dos resultados.
        assert store.carregar_resultados("idealista") == resultado

    def test_atualizar_resultados_substitui_entrada_com_mesmo_link(self, store):
        store.guardar_resultados("idealista", [
            {"titulo": "Título desatualizado", "link": "https://a.pt/1", "status": "EXIGE FIADOR"},
        ])

        resultado = store.atualizar_resultados("idealista", [
            {"titulo": "Título atualizado", "link": "https://a.pt/1", "status": "CONFIRMADO"},
        ])

        assert len(resultado) == 1
        assert resultado[0]["titulo"] == "Título atualizado"
        assert resultado[0]["status"] == "CONFIRMADO"

    def test_atualizar_resultados_com_lista_vazia_nao_apaga_nada(self, store):
        dados = [{"titulo": "Anúncio", "link": "https://a.pt/1"}]
        store.guardar_resultados("idealista", dados)
        resultado = store.atualizar_resultados("idealista", [])
        assert resultado == dados

    def test_ficheiro_corrompido_retorna_lista_vazia(self, store):
        store.ensure_dir()
        (store.data_dir / FONTES["idealista"]["resultados_filename"]).write_text("{ isto nao e json valido", encoding="utf-8")
        assert store.carregar_resultados("idealista") == []

    def test_remover_resultado_apaga_o_anuncio_e_preserva_os_demais(self, store):
        store.guardar_resultados("idealista", [
            {"titulo": "Anúncio A", "link": "https://a.pt/1"},
            {"titulo": "Anúncio B", "link": "https://a.pt/2"},
        ])

        removido = store.remover_resultado("idealista", "https://a.pt/1")

        assert removido is True
        assert store.carregar_resultados("idealista") == [{"titulo": "Anúncio B", "link": "https://a.pt/2"}]

    def test_remover_resultado_tambem_limpa_favorito_e_oculto_associados(self, store):
        link = "https://a.pt/1"
        store.guardar_resultados("idealista", [{"titulo": "Anúncio", "link": link}])
        store.alternar_favorito(link)
        store.alternar_oculto(link)

        store.remover_resultado("idealista", link)

        assert store.carregar_favoritos() == set()
        assert store.carregar_ocultos() == set()

    def test_remover_resultado_com_link_inexistente_nao_faz_nada(self, store):
        dados = [{"titulo": "Anúncio", "link": "https://a.pt/1"}]
        store.guardar_resultados("idealista", dados)
        removido = store.remover_resultado("idealista", "https://a.pt/nao-existe")
        assert removido is False
        assert store.carregar_resultados("idealista") == dados

    def test_atualizar_localizacao_preenche_o_campo_preservando_o_resto(self, store):
        store.guardar_resultados("idealista", [
            {"titulo": "Anúncio", "link": "https://a.pt/1", "status": "CONFIRMADO"},
        ])

        localizacao = {"lat": 41.15, "lon": -8.61, "preciso": True, "texto": "Rua X, 10"}
        store.atualizar_localizacao("idealista", "https://a.pt/1", localizacao)

        resultado = store.carregar_resultados("idealista")[0]
        assert resultado["localizacao"] == localizacao
        assert resultado["status"] == "CONFIRMADO"

    def test_atualizar_localizacao_com_link_inexistente_nao_faz_nada(self, store):
        dados = [{"titulo": "Anúncio", "link": "https://a.pt/1"}]
        store.guardar_resultados("idealista", dados)
        store.atualizar_localizacao("idealista", "https://a.pt/nao-existe", {"lat": 1, "lon": 2})
        assert store.carregar_resultados("idealista") == dados


class TestCacheGeocodificacao:
    def test_cache_vazio_quando_nao_existe(self, store):
        assert store.carregar_cache_geocodificacao() == {}

    def test_guarda_e_recarrega_cache(self, store):
        store.guardar_cache_geocodificacao({"Rua X, Porto": [41.15, -8.61]})
        assert store.carregar_cache_geocodificacao() == {"Rua X, Porto": [41.15, -8.61]}

    def test_permite_guardar_endereco_nao_encontrado_como_none(self, store):
        store.guardar_cache_geocodificacao({"Endereço inexistente": None})
        assert store.carregar_cache_geocodificacao() == {"Endereço inexistente": None}


class TestConfig:
    def test_config_padrao_quando_nao_existe(self, store):
        config = store.carregar_config()
        assert config["idealista"]["url_default"] == URL_BASE_DEFAULT_IDEALISTA
        assert config["idealista"]["url_atual"] == URL_BASE_DEFAULT_IDEALISTA
        assert config["imovirtual"]["url_default"] == URL_BASE_DEFAULT_IMOVIRTUAL
        assert config["imovirtual"]["url_atual"] == URL_BASE_DEFAULT_IMOVIRTUAL

    def test_guardar_url_atual_sobrepoe_url_atual_mas_preserva_default(self, store):
        nova_url = "https://www.idealista.pt/areas/arrendar-casas/porto/"
        config = store.guardar_url_atual("idealista", nova_url)
        assert config["url_atual"] == nova_url
        assert config["url_default"] == URL_BASE_DEFAULT_IDEALISTA

    def test_guardar_url_de_uma_fonte_nao_afeta_a_outra(self, store):
        store.guardar_url_atual("idealista", "https://www.idealista.pt/outra-busca/")
        config = store.carregar_config()
        assert config["imovirtual"]["url_atual"] == URL_BASE_DEFAULT_IMOVIRTUAL

    def test_resetar_url_volta_ao_padrao(self, store):
        store.guardar_url_atual("idealista", "https://www.idealista.pt/outra-busca/")
        config = store.resetar_url("idealista")
        assert config["url_atual"] == URL_BASE_DEFAULT_IDEALISTA

    def test_fonte_desconhecida_levanta_erro(self, store):
        with pytest.raises(ValueError):
            store.guardar_url_atual("olx", "https://www.olx.pt/busca/")

    def test_migra_formato_antigo_sem_aninhamento_por_fonte(self, store):
        # Formato anterior à existência de múltiplas fontes: {"url_atual": "..."}
        # é interpretado como um override só da fonte "idealista".
        store._write_json(store.config_path, {"url_atual": "https://www.idealista.pt/url-antiga/"})
        config = store.carregar_config()
        assert config["idealista"]["url_atual"] == "https://www.idealista.pt/url-antiga/"
        assert config["imovirtual"]["url_atual"] == URL_BASE_DEFAULT_IMOVIRTUAL


class TestFavoritos:
    def test_sem_favoritos_inicialmente(self, store):
        assert store.carregar_favoritos() == set()

    def test_alternar_favorito_adiciona_e_remove(self, store):
        link = "https://www.idealista.pt/imovel/123/"
        assert store.alternar_favorito(link) is True
        assert store.carregar_favoritos() == {link}

        assert store.alternar_favorito(link) is False
        assert store.carregar_favoritos() == set()

    def test_favoritos_multiplos_independentes(self, store):
        store.alternar_favorito("https://a.pt/1")
        store.alternar_favorito("https://a.pt/2")
        assert store.carregar_favoritos() == {"https://a.pt/1", "https://a.pt/2"}


class TestOcultos:
    def test_sem_ocultos_inicialmente(self, store):
        assert store.carregar_ocultos() == set()

    def test_alternar_oculto_adiciona_e_remove(self, store):
        link = "https://www.idealista.pt/imovel/123/"
        assert store.alternar_oculto(link) is True
        assert store.carregar_ocultos() == {link}

        assert store.alternar_oculto(link) is False
        assert store.carregar_ocultos() == set()

    def test_ocultos_multiplos_independentes(self, store):
        store.alternar_oculto("https://a.pt/1")
        store.alternar_oculto("https://a.pt/2")
        assert store.carregar_ocultos() == {"https://a.pt/1", "https://a.pt/2"}

    def test_ocultar_nao_afeta_favoritos(self, store):
        link = "https://a.pt/1"
        store.alternar_favorito(link)
        store.alternar_oculto(link)
        assert store.carregar_favoritos() == {link}
        assert store.carregar_ocultos() == {link}


class TestLog:
    def test_log_mensagem_cria_ficheiro_e_grava_linha(self, store):
        store.log_mensagem("Iniciando teste de log")
        conteudo = store.log_path.read_text(encoding="utf-8")
        assert "Iniciando teste de log" in conteudo

    def test_log_mensagem_acumula_linhas(self, store):
        store.log_mensagem("primeira linha")
        store.log_mensagem("segunda linha")
        linhas = store.log_path.read_text(encoding="utf-8").splitlines()
        assert len(linhas) == 2
