from unittest.mock import MagicMock

import pytest
from google.genai import errors

from enrich import (
    SEGMENTO_EDUCACAO_FINANCEIRA,
    SEGMENTO_INVESTIMENTOS_AVANCADOS,
    enriquecer_usuarios,
    gerar_mensagem,
    montar_cliente_gemini,
)
from settings import Settings


def _usuario(id_, nome="Cliente Teste", qtd_news=0):
    return {
        "id": id_,
        "nome": nome,
        "conta": {"balanco": 100.0},
        "news": [{"id": i, "icone": "", "descricao": ""} for i in range(1, qtd_news + 1)],
    }


def _cliente_fake(texto_resposta):
    """Cliente Gemini falso que sempre devolve o mesmo texto."""
    cliente = MagicMock()
    cliente.models.generate_content.return_value = MagicMock(text=texto_resposta)
    return cliente


def _cliente_que_falha(excecao):
    cliente = MagicMock()
    cliente.models.generate_content.side_effect = excecao
    return cliente


class TestGerarMensagem:
    def test_mensagem_do_gemini_e_usada_quando_sucesso(self):
        cliente = _cliente_fake("Controle seu orçamento, Cliente Teste!")

        mensagem = gerar_mensagem(cliente, "gemini-2.5-flash", _usuario(1), SEGMENTO_EDUCACAO_FINANCEIRA)

        assert mensagem == "Controle seu orçamento, Cliente Teste!"

    def test_prompt_muda_conforme_o_segmento(self):
        cliente = _cliente_fake("resposta qualquer")

        gerar_mensagem(cliente, "gemini-2.5-flash", _usuario(1), SEGMENTO_EDUCACAO_FINANCEIRA)
        prompt_educacao = cliente.models.generate_content.call_args.kwargs["contents"]

        cliente2 = _cliente_fake("resposta qualquer")
        gerar_mensagem(cliente2, "gemini-2.5-flash", _usuario(1), SEGMENTO_INVESTIMENTOS_AVANCADOS)
        prompt_investimento = cliente2.models.generate_content.call_args.kwargs["contents"]

        assert "reserva de emergência" in prompt_educacao
        assert "investimento avançado" in prompt_investimento
        assert prompt_educacao != prompt_investimento

    def test_fallback_diferente_por_segmento_quando_gemini_falha(self):
        cliente_educacao = _cliente_que_falha(RuntimeError("timeout"))
        cliente_investimento = _cliente_que_falha(RuntimeError("timeout"))

        msg_educacao = gerar_mensagem(cliente_educacao, "m", _usuario(1), SEGMENTO_EDUCACAO_FINANCEIRA)
        msg_investimento = gerar_mensagem(cliente_investimento, "m", _usuario(1), SEGMENTO_INVESTIMENTOS_AVANCADOS)

        assert msg_educacao != msg_investimento
        assert "orçamento" in msg_educacao
        assert "invest" in msg_investimento.lower()

    def test_erro_generico_do_gemini_nao_derruba_o_pipeline(self):
        cliente = _cliente_que_falha(ConnectionError("rede fora do ar"))

        mensagem = gerar_mensagem(cliente, "m", _usuario(1), SEGMENTO_EDUCACAO_FINANCEIRA)

        assert mensagem  # recebeu o fallback, não levantou exceção

    def test_resposta_vazia_do_gemini_usa_fallback(self):
        cliente = _cliente_fake("")

        mensagem = gerar_mensagem(cliente, "m", _usuario(1), SEGMENTO_EDUCACAO_FINANCEIRA)

        assert mensagem  # não fica vazia

    def test_mensagem_e_truncada_em_100_caracteres(self):
        texto_longo = "A" * 500
        cliente = _cliente_fake(texto_longo)

        mensagem = gerar_mensagem(cliente, "m", _usuario(1), SEGMENTO_EDUCACAO_FINANCEIRA)

        assert len(mensagem) <= 100

    def test_markdown_e_removido_da_resposta(self):
        cliente = _cliente_fake("**Economize** hoje, `Cliente`!")

        mensagem = gerar_mensagem(cliente, "m", _usuario(1), SEGMENTO_EDUCACAO_FINANCEIRA)

        assert "*" not in mensagem
        assert "`" not in mensagem

    def test_segmento_desconhecido_levanta_erro_claro(self):
        cliente = _cliente_fake("x")

        with pytest.raises(ValueError, match="Segmento desconhecido"):
            gerar_mensagem(cliente, "m", _usuario(1), "segmento_que_nao_existe")


class TestEnriquecerUsuarios:
    def test_enriquece_usuarios_dos_dois_segmentos(self):
        cliente = _cliente_fake("mensagem gerada")
        usuarios_por_segmento = {
            SEGMENTO_EDUCACAO_FINANCEIRA: [_usuario(1)],
            SEGMENTO_INVESTIMENTOS_AVANCADOS: [_usuario(2)],
        }

        resultado = enriquecer_usuarios(cliente, "m", usuarios_por_segmento, icon_url="https://x.com/icon.svg")

        assert len(resultado) == 2
        ids = {u["id"] for u in resultado}
        assert ids == {1, 2}

    def test_news_e_adicionada_preservando_as_existentes(self):
        cliente = _cliente_fake("nova mensagem")
        usuario_com_news = _usuario(1, qtd_news=2)  # já tem news id 1 e 2

        resultado = enriquecer_usuarios(
            cliente, "m", {SEGMENTO_EDUCACAO_FINANCEIRA: [usuario_com_news]}, icon_url="https://x.com/icon.svg"
        )

        news = resultado[0]["news"]
        assert len(news) == 3
        assert news[-1]["id"] == 3  # próximo id sequencial, não sobrescreve

    def test_metadados_de_campanha_sao_anexados_para_auditoria(self):
        cliente = _cliente_fake("mensagem x")

        resultado = enriquecer_usuarios(
            cliente, "m", {SEGMENTO_INVESTIMENTOS_AVANCADOS: [_usuario(5)]}, icon_url="https://x.com/icon.svg"
        )

        assert resultado[0]["_campanha_segmento"] == SEGMENTO_INVESTIMENTOS_AVANCADOS
        assert resultado[0]["_campanha_mensagem"] == "mensagem x"

    def test_usuario_original_nao_e_mutado(self):
        cliente = _cliente_fake("mensagem x")
        usuario_original = _usuario(1)
        news_original_len = len(usuario_original["news"])

        enriquecer_usuarios(
            cliente, "m", {SEGMENTO_EDUCACAO_FINANCEIRA: [usuario_original]}, icon_url="https://x.com/icon.svg"
        )

        assert len(usuario_original["news"]) == news_original_len

    def test_dicionario_de_segmentos_vazio_retorna_lista_vazia(self):
        cliente = _cliente_fake("x")

        resultado = enriquecer_usuarios(cliente, "m", {}, icon_url="https://x.com/icon.svg")

        assert resultado == []


class TestMontarClienteGemini:
    def test_sem_api_key_levanta_erro_claro(self):
        settings = Settings(
            api_url="https://x.com", api_username="admin", api_password="senha-fake",
            timeout_sec=20, saldo_limite_baixo=1000.0,
            saldo_limite_alto=20000.0, opt_out_path="x", audit_log_path="x",
            report_path="x", page_size=50, gemini_api_key=None,
            gemini_model="gemini-2.5-flash", icon_url="https://x.com/i.svg", wrap_news_width=75,
        )

        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            montar_cliente_gemini(settings)