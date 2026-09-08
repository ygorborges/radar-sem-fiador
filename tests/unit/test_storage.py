"""Testes da camada de persistência (Storage), isolados em pasta temporária."""
import pytest

from storage import Storage, URL_BASE_DEFAULT


@pytest.fixture
def store(tmp_path):
    return Storage(tmp_path / "data")


class TestHistorico:
    def test_historico_vazio_quando_nao_existe(self, store):
        assert store.carregar_historico() == set()

    def test_guarda_e_recarrega_historico(self, store):
        store.guardar_historico({"https://a.pt/1", "https://a.pt/2"})
        assert store.carregar_historico() == {"https://a.pt/1", "https://a.pt/2"}


class TestResultados:
    def test_resultados_vazios_quando_nao_existe(self, store):
        assert store.carregar_resultados() == []

    def test_guarda_e_recarrega_resultados(self, store):
        dados = [{"titulo": "Apto T2", "link": "https://a.pt/1"}]
        store.guardar_resultados(dados)
        assert store.carregar_resultados() == dados

    def test_atualizar_resultados_preserva_achados_de_execucoes_anteriores(self, store):
        store.guardar_resultados([
            {"titulo": "Anúncio antigo", "link": "https://a.pt/1", "status": "CONFIRMADO"},
        ])

        resultado = store.atualizar_resultados([
            {"titulo": "Anúncio novo", "link": "https://a.pt/2", "status": "EXIGE FIADOR"},
        ])

        links = {item["link"] for item in resultado}
        assert links == {"https://a.pt/1", "https://a.pt/2"}
        # A varredura seguinte não revisita ".../1" (já está no histórico), mas
        # o anúncio encontrado antes não pode desaparecer dos resultados.
        assert store.carregar_resultados() == resultado

    def test_atualizar_resultados_substitui_entrada_com_mesmo_link(self, store):
        store.guardar_resultados([
            {"titulo": "Título desatualizado", "link": "https://a.pt/1", "status": "EXIGE FIADOR"},
        ])

        resultado = store.atualizar_resultados([
            {"titulo": "Título atualizado", "link": "https://a.pt/1", "status": "CONFIRMADO"},
        ])

        assert len(resultado) == 1
        assert resultado[0]["titulo"] == "Título atualizado"
        assert resultado[0]["status"] == "CONFIRMADO"

    def test_atualizar_resultados_com_lista_vazia_nao_apaga_nada(self, store):
        dados = [{"titulo": "Anúncio", "link": "https://a.pt/1"}]
        store.guardar_resultados(dados)
        resultado = store.atualizar_resultados([])
        assert resultado == dados

    def test_ficheiro_corrompido_retorna_lista_vazia(self, store):
        store.ensure_dir()
        store.resultados_path.write_text("{ isto nao e json valido", encoding="utf-8")
        assert store.carregar_resultados() == []


class TestConfig:
    def test_config_padrao_quando_nao_existe(self, store):
        config = store.carregar_config()
        assert config["url_default"] == URL_BASE_DEFAULT
        assert config["url_atual"] == URL_BASE_DEFAULT

    def test_guardar_url_atual_sobrepoe_url_atual_mas_preserva_default(self, store):
        nova_url = "https://www.idealista.pt/areas/arrendar-casas/porto/"
        config = store.guardar_url_atual(nova_url)
        assert config["url_atual"] == nova_url
        assert config["url_default"] == URL_BASE_DEFAULT

    def test_resetar_url_volta_ao_padrao(self, store):
        store.guardar_url_atual("https://www.idealista.pt/outra-busca/")
        config = store.resetar_url()
        assert config["url_atual"] == URL_BASE_DEFAULT


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
