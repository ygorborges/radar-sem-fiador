"""Testes da consulta de concelho/freguesia (divisão administrativa oficial)."""
import divisoes_administrativas as da


class TestConcelhoDaFreguesia:
    def test_freguesia_simples_sem_uniao(self):
        assert da.concelho_da_freguesia("Bonfim") == "Porto"
        assert da.concelho_da_freguesia("Ramalde") == "Porto"

    def test_uniao_no_formato_oficial(self):
        assert da.concelho_da_freguesia("Aldoar, Foz do Douro e Nevogilde") == "Porto"

    def test_uniao_no_formato_do_idealista_com_travessoes(self):
        # Regressão: era exatamente esse formato ("Cedofeita - Santo
        # Ildefonso - Sé - Miragaia - São Nicolau - Vitória") que o
        # idealista usa, e que precisa bater com o nome oficial
        # ("Cedofeita, Santo Ildefonso, Sé, Miragaia, São Nicolau e
        # Vitória") apesar da pontuação diferente.
        texto = "Cedofeita - Santo Ildefonso - Sé - Miragaia - São Nicolau - Vitória"
        assert da.concelho_da_freguesia(texto) == "Porto"

    def test_uniao_no_formato_do_imovirtual_com_virgulas(self):
        texto = "Cedofeita, Ildefonso, Sé, Miragaia, Nicolau, Vitória"
        assert da.concelho_da_freguesia(texto) == "Porto"

    def test_so_a_paroquia_antiga_sem_a_uniao_completa(self):
        # O anúncio só cita "Aldoar" (paróquia antiga), não a união completa
        # "Aldoar, Foz do Douro e Nevogilde" — ainda deve resolver pro
        # concelho certo.
        assert da.concelho_da_freguesia("Aldoar") == "Porto"

    def test_fanzeres_e_gondomar_nao_porto(self):
        # O caso relatado pelo usuário: Fânzeres não é do concelho do Porto.
        assert da.concelho_da_freguesia("Fânzeres e São Pedro da Cova") == "Gondomar"
        assert da.concelho_da_freguesia("Fânzeres") == "Gondomar"

    def test_cidade_da_maia_e_maia_nao_porto(self):
        assert da.concelho_da_freguesia("Cidade da Maia") == "Maia"

    def test_freguesias_de_gaia(self):
        assert da.concelho_da_freguesia("Santa Marinha e São Pedro da Afurada") == "Vila Nova de Gaia"
        assert da.concelho_da_freguesia("Mafamude e Vilar do Paraíso") == "Vila Nova de Gaia"
        assert da.concelho_da_freguesia("Mafamude") == "Vila Nova de Gaia"

    def test_freguesia_desconhecida_devolve_none(self):
        assert da.concelho_da_freguesia("Bairro Que Não Existe Em Lugar Nenhum") is None

    def test_nome_ambiguo_entre_concelhos_devolve_none(self):
        # Regressão: "Paranhos" é freguesia tanto do Porto quanto de Seia —
        # sem a checagem de ambiguidade na correspondência de nome inteiro,
        # o concelho processado por último (ordem alfabética) "roubava" a
        # freguesia do Porto, atribuindo por engano o anúncio a Seia.
        assert da.concelho_da_freguesia("Paranhos") is None

    def test_nome_que_colide_com_componente_de_uniao_de_outro_concelho_devolve_none(self):
        # "Santa Marinha" é freguesia própria de Ribeira de Pena, mas também
        # é um dos nomes que compõem a união "Santa Marinha e São Pedro da
        # Afurada" de Vila Nova de Gaia — citado sozinho, sem o resto da
        # união, é ambíguo demais pra decidir com confiança.
        assert da.concelho_da_freguesia("Santa Marinha") is None


class TestDesempatePorDicaDeCidade:
    def test_dica_desempata_nome_ambiguo(self):
        # "Oliveira do Douro" existe tanto em Cinfães quanto em Vila Nova de
        # Gaia — achado real: o idealista, pra anúncios fora da cidade do
        # Porto, junta concelho e distrito no último nível da localização
        # ("Vila Nova de Gaia, Porto"). Mesmo não servindo como concelho
        # isolado, esse texto ainda contém o nome certo pra desempatar.
        assert da.concelho_da_freguesia("Oliveira do Douro", dica_cidade="Vila Nova de Gaia, Porto") == "Vila Nova de Gaia"
        assert da.concelho_da_freguesia("Oliveira do Douro", dica_cidade="Cinfães, Viseu") == "Cinfães"

    def test_dica_que_nao_bate_com_nenhum_candidato_continua_none(self):
        assert da.concelho_da_freguesia("Oliveira do Douro", dica_cidade="Lisboa") is None

    def test_dica_ambigua_ela_mesma_continua_none(self):
        # A dica é só o distrito ("Porto"), que não identifica nenhum dos
        # dois candidatos por nome — não deve inventar uma resposta.
        assert da.concelho_da_freguesia("Oliveira do Douro", dica_cidade="Porto") is None

    def test_sem_dica_mantem_o_comportamento_conservador(self):
        assert da.concelho_da_freguesia("Oliveira do Douro") is None

    def test_texto_vazio_devolve_none(self):
        assert da.concelho_da_freguesia("") is None
        assert da.concelho_da_freguesia(None) is None


class TestCanonicalizarFreguesia:
    def test_formatos_diferentes_convergem_pro_mesmo_nome_oficial(self):
        formato_idealista = "Cedofeita - Santo Ildefonso - Sé - Miragaia - São Nicolau - Vitória"
        formato_imovirtual = "Cedofeita, Ildefonso, Sé, Miragaia, Nicolau, Vitória"
        assert da.canonicalizar_freguesia(formato_idealista) == da.canonicalizar_freguesia(formato_imovirtual)

    def test_paroquia_antiga_canonicaliza_para_a_uniao_completa(self):
        assert da.canonicalizar_freguesia("Aldoar") == "Aldoar, Foz do Douro e Nevogilde"

    def test_freguesia_desconhecida_mantem_o_texto_original(self):
        texto = "Bairro Que Não Existe Em Lugar Nenhum"
        assert da.canonicalizar_freguesia(texto) == texto


class TestConcelhosFreguesias:
    def test_cobre_todos_os_concelhos_da_area_metropolitana_do_porto(self):
        for concelho in ("Porto", "Vila Nova de Gaia", "Maia", "Gondomar", "Matosinhos", "Valongo"):
            assert concelho in da.CONCELHOS_FREGUESIAS
            assert len(da.CONCELHOS_FREGUESIAS[concelho]) > 0

    def test_total_de_freguesias_bate_com_o_numero_oficial_do_pais(self):
        total = sum(len(fs) for fs in da.CONCELHOS_FREGUESIAS.values())
        assert total == 3092
