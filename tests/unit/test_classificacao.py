"""Testes das funções puras de classificação de fiador, comuns a todas as fontes."""
import classificacao


class TestLimparTextoCookieBanner:
    def test_remove_texto_padrao_de_cookies(self):
        texto = "No idealista utilizamos cookies para melhorar a sua experiência. política de cookies. Resto do anúncio."
        limpo = classificacao.limpar_texto_cookie_banner(texto)
        assert "cookies" not in limpo.lower()
        assert "Resto do anúncio" in limpo

    def test_texto_vazio_retorna_vazio(self):
        assert classificacao.limpar_texto_cookie_banner("") == ""

    def test_texto_none_retorna_none(self):
        assert classificacao.limpar_texto_cookie_banner(None) is None

    def test_colapsa_espacos_multiplos(self):
        assert classificacao.limpar_texto_cookie_banner("a   b\n\nc") == "a b c"


class TestExtrairBlocoDoAnuncio:
    def test_corta_a_partir_do_primeiro_marcador(self):
        texto = "Cabeçalho irrelevante Descrição: apartamento fantástico sem fiador"
        bloco = classificacao.extrair_bloco_do_anuncio(texto)
        assert bloco.startswith("Descrição")

    def test_sem_marcador_retorna_texto_completo(self):
        texto = "Apenas um texto qualquer sem marcadores conhecidos"
        assert classificacao.extrair_bloco_do_anuncio(texto) == texto

    def test_texto_vazio_retorna_vazio(self):
        assert classificacao.extrair_bloco_do_anuncio("") == ""


class TestExtrairTipologia:
    def test_extrai_t2_do_titulo(self):
        assert classificacao.extrair_tipologia("Apartamento T2 em Cedofeita", "") == "T2"

    def test_extrai_tipologia_do_texto_quando_titulo_nao_tem(self):
        assert classificacao.extrair_tipologia("Imóvel para arrendar", "Trata-se de um T3 renovado") == "T3"

    def test_sem_tipologia_retorna_indefinida(self):
        assert classificacao.extrair_tipologia("Excelente oportunidade", "sem indicação de tipologia aqui") == "Indefinida"

    def test_numero_de_rua_nao_e_confundido_com_tipologia(self):
        # Regressão: havia um padrão de reserva que pegava o primeiro número
        # solto no texto (aqui, o "60" do número da porta), virando "T60".
        titulo = "Arrendamento de apartamento na Rua de Faria Guimarães, 60"
        texto = "Fica a 2 minutos da estação de metro. Excelente localização."
        assert classificacao.extrair_tipologia(titulo, texto) == "Indefinida"


class TestExtrairTipoAnunciante:
    def test_detecta_particular(self):
        assert classificacao.extrair_tipo_anunciante("Anúncio de anunciante particular, sem agência.") == "Particular"

    def test_detecta_profissional(self):
        assert classificacao.extrair_tipo_anunciante("Imobiliária profissional com vários imóveis.") == "Profissional"

    def test_texto_vazio_retorna_desconhecido(self):
        assert classificacao.extrair_tipo_anunciante("") == "Desconhecido"

    def test_sem_pista_retorna_desconhecido(self):
        assert classificacao.extrair_tipo_anunciante("Um apartamento com vista para o rio.") == "Desconhecido"


class TestDetectarBloqueio:
    def test_detecta_cloudflare(self):
        assert classificacao.detectar_bloqueio("Erro Cloudflare Ray ID: 123456") is True

    def test_detecta_demasiados_pedidos(self):
        assert classificacao.detectar_bloqueio("Demasiados pedidos, aguarde uns momentos.") is True

    def test_texto_normal_nao_e_bloqueio(self):
        assert classificacao.detectar_bloqueio("Apartamento T2 com boa localização.") is False

    def test_texto_vazio_nao_e_bloqueio(self):
        assert classificacao.detectar_bloqueio("") is False


class TestDetectarAnuncioIndisponivel:
    def test_detecta_anuncio_ja_nao_disponivel(self):
        assert classificacao.detectar_anuncio_indisponivel("Este anúncio já não está disponível.") is True

    def test_detecta_imovel_ja_nao_disponivel(self):
        assert classificacao.detectar_anuncio_indisponivel("Este imóvel já não está disponível na plataforma.") is True

    def test_detecta_anuncio_removido(self):
        assert classificacao.detectar_anuncio_indisponivel("Este anúncio foi removido pelo anunciante.") is True

    def test_detecta_pagina_nao_encontrada(self):
        assert classificacao.detectar_anuncio_indisponivel("Erro 404 - Página não encontrada.") is True

    def test_texto_normal_nao_e_indisponivel(self):
        assert classificacao.detectar_anuncio_indisponivel("Apartamento T2 com boa localização, sem fiador.") is False

    def test_texto_vazio_nao_e_indisponivel(self):
        assert classificacao.detectar_anuncio_indisponivel("") is False
        assert classificacao.detectar_anuncio_indisponivel(None) is False


class TestAnalisarFiador:
    def test_texto_vazio(self):
        passou, status, trecho = classificacao.analisar_fiador("")
        assert passou is False
        assert status == "ERRO_TEXTO_VAZIO"
        assert trecho is None

    def test_bloqueio_anti_bot(self):
        passou, status, trecho = classificacao.analisar_fiador("Descrição: Cloudflare Ray ID bloqueou o pedido.")
        assert passou is False
        assert status == "BLOQUEADO_POR_ANTI_BOT"

    def test_confirma_dispensa_explicita_de_fiador(self):
        texto = "Descrição: apartamento moderno, sem fiador, aceita-se caução reforçada."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"
        assert trecho is not None

    def test_sem_mencao_a_fiador(self):
        texto = "Descrição: apartamento moderno com vista para o rio, dois quartos, garagem."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "SEM MENÇÃO (Não cita fiador)"
        assert trecho is None

    def test_exige_fiador(self):
        texto = "Descrição: é necessário apresentar fiador para assinatura do contrato."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "EXIGE FIADOR"
        assert trecho is not None

    def test_fiador_no_plural_e_reconhecido(self):
        # O Imovirtual usa com frequência a forma plural: "Fiadores Idóneos".
        texto = "Descrição: Exige-se fiadores idóneos/caução."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "EXIGE FIADOR"
        assert "fiadores" in trecho.lower()

    def test_mencao_de_meses_de_caucao_nao_confirma_dispensa_de_fiador(self):
        # Regressão: "X meses de caução" é uma cláusula de pagamento comum e
        # NÃO significa que o fiador foi dispensado — não deve ser
        # confundida com "caução reforçada" (que substitui o fiador).
        texto = "Descrição: Condições de arrendamento: 2 meses de renda 2 meses de caução Fiador."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "EXIGE FIADOR"

    def test_mencao_de_rendas_adiantadas_nao_confirma_dispensa_de_fiador(self):
        texto = "Descrição: são exigidas 3 rendas adiantadas e fiador para aprovação do contrato."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "EXIGE FIADOR"

    def test_caucao_reforcada_ainda_confirma_dispensa_de_fiador(self):
        texto = "Descrição: aceita-se caução reforçada em substituição do fiador."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_reforco_de_caucao_confirma_dispensa_de_fiador(self):
        # Regressão: "cau[çc][ãao]" faltava um caractere para casar com a
        # palavra "caução" (ç+ã+o) antes do espaço seguinte, então esse
        # padrão nunca disparava em texto real acentuado.
        texto = "Descrição: aceitamos reforço de caução em vez de fiador."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_substituivel_por_caucao_confirma_dispensa_de_fiador(self):
        texto = "Descrição: fiador substituível por caução reforçada, sem problema."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_nao_exige_fiador_terceira_pessoa_confirma(self):
        # Regressão: só "não exijo fiador" (1ª pessoa) era reconhecido; a
        # forma bem mais comum em anúncios, na 3ª pessoa ("não exige"),
        # não tinha nenhum padrão correspondente e caía em EXIGE FIADOR.
        texto = "Descrição: o senhorio não exige fiador para este contrato."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_nao_exigimos_apresentacao_de_fiador_confirma(self):
        texto = "Descrição: não exigimos a apresentação de fiador ao inquilino."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_fiador_nao_e_necessario_forma_pos_posta_confirma(self):
        texto = "Descrição: fiador não é necessário para este imóvel."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_fiador_nao_e_obrigatorio_forma_pos_posta_confirma(self):
        texto = "Descrição: fiador não é obrigatório neste contrato."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_isento_de_fiador_confirma(self):
        texto = "Descrição: imóvel isento de fiador."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_fiador_opcional_confirma(self):
        texto = "Descrição: fiador opcional, sujeito a análise de crédito."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_dispensa_fiador_com_texto_pelo_meio_confirma(self):
        texto = "Descrição: o proprietário dispensa a apresentação de fiador para este arrendamento."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "CONFIRMADO (Explícito/Flexível)"

    def test_dispensa_de_assunto_nao_relacionado_nao_confirma_fiador(self):
        # Regressão: o padrão antigo "dispensa.*fiador" não tinha limite de
        # distância, então um "dispensa" sobre outro assunto qualquer,
        # numa frase completamente diferente, casava com um "fiador"
        # exigido bem mais adiante no texto.
        texto = (
            "Descrição: O condomínio dispensa a limpeza extra este mês. "
            "Foto profissional. Foi pedido ao inquilino anterior fiador "
            "e vamos manter essa exigência."
        )
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "EXIGE FIADOR"

    def test_sem_outro_atributo_na_mesma_frase_do_fiador_nao_confirma(self):
        # "sem" aqui qualifica "mobília", não "fiador" — não deve confirmar.
        texto = "Descrição: apartamento sem mobília, com fiador obrigatório."
        passou, status, trecho = classificacao.analisar_fiador(texto)
        assert passou is True
        assert status == "EXIGE FIADOR"
