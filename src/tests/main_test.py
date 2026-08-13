from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import enrich
import segment
import load as load_module
from main import executar_pipeline
from settings import Settings


def _settings(tmp_path, opt_out_path=None):
    return Settings(
        api_url="https://users-api-python.onrender.com",
        api_username="admin",
        api_password="senha-fake",
        timeout_sec=20,
        saldo_limite_baixo=1000.0,
        saldo_limite_alto=20000.0,
        opt_out_path=opt_out_path or str(tmp_path / "opt_out.csv"),
        audit_log_path=str(tmp_path / "logs" / "audit_log.jsonl"),
        report_path=str(tmp_path / "report_etl.csv"),
        page_size=50,
        gemini_api_key="fake-key",
        gemini_model="gemini-2.5-flash",
        icon_url="https://exemplo.com/icon.svg",
        wrap_news_width=75,
    )


def _usuario(id_, balanco):
    return {"id": id_, "nome": f"Usuario {id_}", "conta": {"balanco": balanco}, "news": []}


class TestFluxoCompleto:
    @patch("main.load_module.carregar_usuarios")
    @patch("main.enrich.enriquecer_usuarios")
    @patch("main.enrich.montar_cliente_gemini")
    @patch("main.extract.buscar_todos_usuarios")
    def test_pipeline_chama_os_quatro_estagios_em_ordem(
        self, mock_extract, mock_montar_cliente, mock_enriquecer, mock_carregar, tmp_path
    ):
        mock_extract.return_value = [_usuario(1, balanco=100.0)]  # educação financeira
        mock_montar_cliente.return_value = MagicMock()
        mock_enriquecer.return_value = [_usuario(1, balanco=100.0)]
        mock_carregar.return_value = load_module.LoadResultado(total=1, sucesso=1, falha=0)

        executar_pipeline(_settings(tmp_path))

        mock_extract.assert_called_once()
        mock_montar_cliente.assert_called_once()
        mock_enriquecer.assert_called_once()
        mock_carregar.assert_called_once()

    @patch("main.load_module.carregar_usuarios")
    @patch("main.enrich.enriquecer_usuarios")
    @patch("main.enrich.montar_cliente_gemini")
    @patch("main.extract.buscar_todos_usuarios")
    def test_segmentacao_correta_e_passada_para_enrich(
        self, mock_extract, mock_montar_cliente, mock_enriquecer, mock_carregar, tmp_path
    ):
        mock_extract.return_value = [
            _usuario(1, balanco=100.0),     # educação financeira
            _usuario(2, balanco=50000.0),   # investimentos avançados
            _usuario(3, balanco=5000.0),    # faixa neutra, não deve entrar
        ]
        mock_montar_cliente.return_value = MagicMock()
        mock_enriquecer.return_value = []
        mock_carregar.return_value = load_module.LoadResultado(total=0, sucesso=0, falha=0)

        executar_pipeline(_settings(tmp_path))

        usuarios_por_segmento = mock_enriquecer.call_args.args[2]
        ids_educacao = {u["id"] for u in usuarios_por_segmento[enrich.SEGMENTO_EDUCACAO_FINANCEIRA]}
        ids_investimento = {u["id"] for u in usuarios_por_segmento[enrich.SEGMENTO_INVESTIMENTOS_AVANCADOS]}

        assert ids_educacao == {1}
        assert ids_investimento == {2}


class TestAtalhoSemElegiveis:
    @patch("main.load_module.carregar_usuarios")
    @patch("main.enrich.enriquecer_usuarios")
    @patch("main.enrich.montar_cliente_gemini")
    @patch("main.extract.buscar_todos_usuarios")
    def test_sem_elegiveis_nao_chama_gemini_nem_load(
        self, mock_extract, mock_montar_cliente, mock_enriquecer, mock_carregar, tmp_path
    ):
        mock_extract.return_value = [_usuario(1, balanco=5000.0)]  # faixa neutra -- ninguém elegível

        executar_pipeline(_settings(tmp_path))

        mock_montar_cliente.assert_not_called()
        mock_enriquecer.assert_not_called()
        mock_carregar.assert_not_called()

    @patch("main.extract.buscar_todos_usuarios")
    def test_sem_elegiveis_ainda_assim_salva_relatorio(self, mock_extract, tmp_path):
        mock_extract.return_value = [_usuario(1, balanco=5000.0)]
        settings = _settings(tmp_path)

        executar_pipeline(settings)

        assert Path(settings.report_path).exists()


class TestRelatorio:
    @patch("main.load_module.carregar_usuarios")
    @patch("main.enrich.enriquecer_usuarios")
    @patch("main.enrich.montar_cliente_gemini")
    @patch("main.extract.buscar_todos_usuarios")
    def test_relatorio_acumula_linhas_entre_execucoes_em_vez_de_sobrescrever(
        self, mock_extract, mock_montar_cliente, mock_enriquecer, mock_carregar, tmp_path
    ):
        mock_extract.return_value = [_usuario(1, balanco=100.0)]
        mock_montar_cliente.return_value = MagicMock()
        mock_enriquecer.return_value = [_usuario(1, balanco=100.0)]
        mock_carregar.return_value = load_module.LoadResultado(total=1, sucesso=1, falha=0)
        settings = _settings(tmp_path)

        executar_pipeline(settings)
        executar_pipeline(settings)

        conteudo = Path(settings.report_path).read_text().strip().splitlines()
        assert len(conteudo) == 3  # header + 2 execuções


class TestOptOutIntegrado:
    @patch("main.load_module.carregar_usuarios")
    @patch("main.enrich.enriquecer_usuarios")
    @patch("main.enrich.montar_cliente_gemini")
    @patch("main.extract.buscar_todos_usuarios")
    def test_usuario_na_lista_de_supressao_nao_chega_no_enrich(
        self, mock_extract, mock_montar_cliente, mock_enriquecer, mock_carregar, tmp_path
    ):
        opt_out_path = tmp_path / "opt_out.csv"
        opt_out_path.write_text("user_id\n1\n")

        mock_extract.return_value = [_usuario(1, balanco=100.0), _usuario(2, balanco=100.0)]
        mock_montar_cliente.return_value = MagicMock()
        mock_enriquecer.return_value = []
        mock_carregar.return_value = load_module.LoadResultado(total=0, sucesso=0, falha=0)

        executar_pipeline(_settings(tmp_path, opt_out_path=str(opt_out_path)))

        usuarios_por_segmento = mock_enriquecer.call_args.args[2]
        ids_educacao = {u["id"] for u in usuarios_por_segmento[enrich.SEGMENTO_EDUCACAO_FINANCEIRA]}

        assert 1 not in ids_educacao
        assert 2 in ids_educacao