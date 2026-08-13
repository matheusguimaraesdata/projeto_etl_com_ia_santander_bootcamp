import json
from unittest.mock import patch

import pytest

from load import atualizar_usuario, autenticar, carregar_usuarios, registrar_auditoria
from settings import Settings


def _settings(audit_log_path="logs/audit_log.jsonl"):
    return Settings(
        api_url="https://users-api-python.onrender.com",
        api_username="admin",
        api_password="senha-fake",
        timeout_sec=20,
        saldo_limite_baixo=1000.0,
        saldo_limite_alto=20000.0,
        opt_out_path="data/opt_out.csv",
        audit_log_path=audit_log_path,
        report_path="report_etl.csv",
        page_size=50,
        gemini_api_key="fake-key",
        gemini_model="gemini-2.5-flash",
        icon_url="https://exemplo.com/icon.svg",
        wrap_news_width=75,
    )


def _usuario_enriquecido(id_=1, segmento="educacao_financeira", mensagem="mensagem x"):
    return {
        "id": id_,
        "nome": "Cliente Teste",
        "news": [{"id": 1, "icone": "https://x.com/i.svg", "descricao": mensagem}],
        "_campanha_segmento": segmento,
        "_campanha_mensagem": mensagem,
    }


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class TestAutenticar:
    @patch("load.requests.post")
    def test_login_bem_sucedido_retorna_token(self, mock_post):
        mock_post.return_value = _FakeResponse(200, {"access_token": "token-123", "token_type": "bearer"})

        token = autenticar(_settings())

        assert token == "token-123"

    @patch("load.requests.post")
    def test_login_envia_username_e_password_no_formato_oauth2(self, mock_post):
        mock_post.return_value = _FakeResponse(200, {"access_token": "t"})

        autenticar(_settings())

        dados_enviados = mock_post.call_args.kwargs["data"]
        assert dados_enviados == {"username": "admin", "password": "senha-fake"}

    @patch("load.requests.post")
    def test_credenciais_invalidas_levanta_erro_claro(self, mock_post):
        mock_post.return_value = _FakeResponse(401, text="Usuário ou senha inválidos")

        with pytest.raises(RuntimeError, match="401"):
            autenticar(_settings())

    @patch("load.requests.post")
    def test_resposta_sem_access_token_levanta_erro(self, mock_post):
        mock_post.return_value = _FakeResponse(200, {"token_type": "bearer"})  # sem access_token

        with pytest.raises(RuntimeError, match="access_token"):
            autenticar(_settings())


class TestAtualizarUsuario:
    @patch("load.requests.patch")
    def test_patch_bem_sucedido_retorna_true(self, mock_patch):
        mock_patch.return_value = _FakeResponse(200)

        resultado = atualizar_usuario(_settings(), "token-abc", _usuario_enriquecido())

        assert resultado is True

    @patch("load.requests.patch")
    def test_falha_no_patch_retorna_false_sem_levantar_excecao(self, mock_patch):
        mock_patch.return_value = _FakeResponse(500, text="erro interno")

        resultado = atualizar_usuario(_settings(), "token-abc", _usuario_enriquecido())

        assert resultado is False

    @patch("load.requests.patch")
    def test_envia_apenas_o_campo_news_no_payload(self, mock_patch):
        mock_patch.return_value = _FakeResponse(200)
        usuario = _usuario_enriquecido()

        atualizar_usuario(_settings(), "token-abc", usuario)

        payload_enviado = mock_patch.call_args.kwargs["json"]
        assert list(payload_enviado.keys()) == ["news"]
        assert payload_enviado["news"] == usuario["news"]

    @patch("load.requests.patch")
    def test_envia_token_no_header_authorization(self, mock_patch):
        mock_patch.return_value = _FakeResponse(200)

        atualizar_usuario(_settings(), "token-abc", _usuario_enriquecido())

        headers = mock_patch.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer token-abc"

    @patch("load.requests.patch")
    def test_url_usa_o_id_correto_do_usuario(self, mock_patch):
        mock_patch.return_value = _FakeResponse(200)

        atualizar_usuario(_settings(), "token-abc", _usuario_enriquecido(id_=42))

        url_chamada = mock_patch.call_args.args[0] if mock_patch.call_args.args else mock_patch.call_args.kwargs.get("url")
        # a URL é passada como primeiro argumento posicional em requests.patch(url, ...)
        assert "42" in str(mock_patch.call_args)


class TestRegistrarAuditoria:
    def test_grava_uma_linha_jsonl_com_os_campos_esperados(self, tmp_path):
        caminho_log = tmp_path / "audit_log.jsonl"

        registrar_auditoria(_usuario_enriquecido(id_=7, segmento="investimentos_avancados"), sucesso=True, audit_log_path=str(caminho_log))

        linhas = caminho_log.read_text().strip().splitlines()
        assert len(linhas) == 1

        entrada = json.loads(linhas[0])
        assert entrada["usuario_id"] == 7
        assert entrada["segmento"] == "investimentos_avancados"
        assert entrada["sucesso"] is True
        assert "timestamp" in entrada

    def test_chamadas_sucessivas_acumulam_linhas_em_vez_de_sobrescrever(self, tmp_path):
        caminho_log = tmp_path / "audit_log.jsonl"

        registrar_auditoria(_usuario_enriquecido(id_=1), True, str(caminho_log))
        registrar_auditoria(_usuario_enriquecido(id_=2), False, str(caminho_log))

        linhas = caminho_log.read_text().strip().splitlines()
        assert len(linhas) == 2

    def test_cria_diretorio_do_log_automaticamente_se_nao_existir(self, tmp_path):
        caminho_log = tmp_path / "pasta_que_nao_existe" / "audit_log.jsonl"

        registrar_auditoria(_usuario_enriquecido(), True, str(caminho_log))

        assert caminho_log.exists()


class TestCarregarUsuarios:
    @patch("load.requests.patch")
    @patch("load.requests.post")
    def test_lista_vazia_nao_autentica_e_retorna_zerado(self, mock_post, mock_patch, tmp_path):
        resultado = carregar_usuarios(_settings(audit_log_path=str(tmp_path / "log.jsonl")), [])

        assert resultado.total == 0
        mock_post.assert_not_called()

    @patch("load.requests.patch")
    @patch("load.requests.post")
    def test_processa_todos_e_conta_sucesso_e_falha_corretamente(self, mock_post, mock_patch, tmp_path):
        mock_post.return_value = _FakeResponse(200, {"access_token": "t"})
        mock_patch.side_effect = [
            _FakeResponse(200),  # usuário 1: sucesso
            _FakeResponse(500),  # usuário 2: falha
            _FakeResponse(200),  # usuário 3: sucesso
        ]
        usuarios = [_usuario_enriquecido(id_=1), _usuario_enriquecido(id_=2), _usuario_enriquecido(id_=3)]

        resultado = carregar_usuarios(_settings(audit_log_path=str(tmp_path / "log.jsonl")), usuarios)

        assert resultado.total == 3
        assert resultado.sucesso == 2
        assert resultado.falha == 1

    @patch("load.requests.patch")
    @patch("load.requests.post")
    def test_uma_falha_nao_impede_o_processamento_dos_demais(self, mock_post, mock_patch, tmp_path):
        mock_post.return_value = _FakeResponse(200, {"access_token": "t"})
        mock_patch.side_effect = [_FakeResponse(500), _FakeResponse(200)]
        usuarios = [_usuario_enriquecido(id_=1), _usuario_enriquecido(id_=2)]

        resultado = carregar_usuarios(_settings(audit_log_path=str(tmp_path / "log.jsonl")), usuarios)

        assert mock_patch.call_count == 2  # o segundo usuário FOI tentado, mesmo o primeiro falhando
        assert resultado.total == 2

    @patch("load.requests.patch")
    @patch("load.requests.post")
    def test_todos_os_usuarios_geram_entrada_no_log_de_auditoria(self, mock_post, mock_patch, tmp_path):
        mock_post.return_value = _FakeResponse(200, {"access_token": "t"})
        mock_patch.return_value = _FakeResponse(200)
        caminho_log = tmp_path / "log.jsonl"
        usuarios = [_usuario_enriquecido(id_=1), _usuario_enriquecido(id_=2)]

        carregar_usuarios(_settings(audit_log_path=str(caminho_log)), usuarios)

        linhas = caminho_log.read_text().strip().splitlines()
        assert len(linhas) == 2