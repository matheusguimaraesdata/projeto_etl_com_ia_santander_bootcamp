import pytest

from segment import carregar_opt_out_ids, selecionar_audiencia


LIMITE_BAIXO = 1000.0
LIMITE_ALTO = 20000.0


def _usuario(id_, balanco, qtd_news=0):
    """Helper: monta um usuário no formato da API com o mínimo necessário."""
    return {
        "id": id_,
        "nome": f"Usuario {id_}",
        "conta": {"balanco": balanco, "limite": 0.0, "agencia": "0001", "numero": "0"},
        "news": [{"id": i, "icone": "", "descricao": ""} for i in range(qtd_news)],
    }


class TestSegmentoEducacaoFinanceira:
    def test_saldo_baixo_positivo_entra_em_educacao_financeira(self):
        usuarios = [_usuario(1, balanco=500.0)]
        resultado = selecionar_audiencia(usuarios, set(), LIMITE_BAIXO, LIMITE_ALTO)

        assert resultado.total_educacao_financeira == 1
        assert resultado.usuarios_educacao_financeira[0]["id"] == 1
        assert resultado.total_investimentos_avancados == 0

    def test_saldo_negativo_tambem_entra_em_educacao_financeira(self):
        usuarios = [_usuario(1, balanco=-350.0)]
        resultado = selecionar_audiencia(usuarios, set(), LIMITE_BAIXO, LIMITE_ALTO)

        assert resultado.total_educacao_financeira == 1


class TestSegmentoInvestimentosAvancados:
    def test_saldo_alto_entra_em_investimentos_avancados(self):
        usuarios = [_usuario(1, balanco=50000.0)]
        resultado = selecionar_audiencia(usuarios, set(), LIMITE_BAIXO, LIMITE_ALTO)

        assert resultado.total_investimentos_avancados == 1
        assert resultado.usuarios_investimentos_avancados[0]["id"] == 1
        assert resultado.total_educacao_financeira == 0


class TestFaixaNeutra:
    def test_saldo_entre_os_dois_limites_nao_entra_em_nenhuma_campanha(self):
        usuarios = [_usuario(1, balanco=5000.0)]  # entre 1000 e 20000
        resultado = selecionar_audiencia(usuarios, set(), LIMITE_BAIXO, LIMITE_ALTO)

        assert resultado.total_elegiveis == 0
        assert resultado.excluidos_por_faixa_neutra == 1

    def test_saldo_exatamente_no_limite_baixo_e_neutro_nao_educacao(self):
        # regra é "<", não "<=" — fronteira exclusiva, testada explicitamente
        usuarios = [_usuario(1, balanco=LIMITE_BAIXO)]
        resultado = selecionar_audiencia(usuarios, set(), LIMITE_BAIXO, LIMITE_ALTO)

        assert resultado.total_educacao_financeira == 0
        assert resultado.excluidos_por_faixa_neutra == 1

    def test_saldo_exatamente_no_limite_alto_e_neutro_nao_investimento(self):
        usuarios = [_usuario(1, balanco=LIMITE_ALTO)]
        resultado = selecionar_audiencia(usuarios, set(), LIMITE_BAIXO, LIMITE_ALTO)

        assert resultado.total_investimentos_avancados == 0
        assert resultado.excluidos_por_faixa_neutra == 1


class TestExclusoesTransversais:
    def test_usuario_que_ja_recebeu_news_e_excluido_mesmo_com_saldo_elegivel(self):
        usuarios = [_usuario(1, balanco=200.0, qtd_news=2)]
        resultado = selecionar_audiencia(usuarios, set(), LIMITE_BAIXO, LIMITE_ALTO)

        assert resultado.total_elegiveis == 0
        assert resultado.excluidos_por_news_existente == 1

    def test_usuario_na_lista_de_supressao_e_excluido_mesmo_elegivel_por_saldo(self):
        usuarios = [_usuario(7, balanco=100.0)]
        resultado = selecionar_audiencia(usuarios, {7}, LIMITE_BAIXO, LIMITE_ALTO)

        assert resultado.total_elegiveis == 0
        assert resultado.excluidos_por_supressao == 1

    def test_conta_ausente_trata_saldo_como_zero_em_vez_de_quebrar(self):
        usuario_sem_conta = {"id": 1, "nome": "Sem Conta", "news": []}
        resultado = selecionar_audiencia([usuario_sem_conta], set(), LIMITE_BAIXO, LIMITE_ALTO)

        # saldo 0.0 < 1000 -> educação financeira
        assert resultado.total_educacao_financeira == 1


class TestValidacaoDeLimites:
    def test_limite_baixo_maior_que_limite_alto_levanta_erro(self):
        with pytest.raises(ValueError, match="saldo_limite_baixo"):
            selecionar_audiencia([], set(), saldo_limite_baixo=30000, saldo_limite_alto=1000)

    def test_limites_iguais_tambem_levanta_erro(self):
        with pytest.raises(ValueError, match="saldo_limite_baixo"):
            selecionar_audiencia([], set(), saldo_limite_baixo=5000, saldo_limite_alto=5000)


class TestListaVazia:
    def test_lista_vazia_de_usuarios_nao_quebra_e_retorna_zerado(self):
        resultado = selecionar_audiencia([], set(), LIMITE_BAIXO, LIMITE_ALTO)

        assert resultado.total_avaliados == 0
        assert resultado.total_elegiveis == 0


class TestFunilCompleto:
    def test_todas_as_categorias_somam_o_total_avaliado(self):
        usuarios = [
            _usuario(1, balanco=500.0),               # educação financeira
            _usuario(2, balanco=-200.0),               # educação financeira
            _usuario(3, balanco=50000.0),              # investimentos avançados
            _usuario(4, balanco=5000.0),                # faixa neutra
            _usuario(5, balanco=100.0, qtd_news=1),     # excluído: já recebeu news
            _usuario(6, balanco=100.0),                 # excluído: supressão
        ]
        resultado = selecionar_audiencia(usuarios, opt_out_ids={6}, saldo_limite_baixo=LIMITE_BAIXO, saldo_limite_alto=LIMITE_ALTO)

        assert resultado.total_avaliados == 6
        assert resultado.total_educacao_financeira == 2
        assert resultado.total_investimentos_avancados == 1
        assert resultado.excluidos_por_faixa_neutra == 1
        assert resultado.excluidos_por_news_existente == 1
        assert resultado.excluidos_por_supressao == 1

        soma = (
            resultado.total_educacao_financeira
            + resultado.total_investimentos_avancados
            + resultado.excluidos_por_faixa_neutra
            + resultado.excluidos_por_news_existente
            + resultado.excluidos_por_supressao
        )
        assert soma == resultado.total_avaliados


class TestCarregarOptOutIds:
    def test_le_ids_corretamente_do_csv(self, tmp_path):
        csv_path = tmp_path / "opt_out.csv"
        csv_path.write_text("user_id\n3\n7\n15\n")

        assert carregar_opt_out_ids(str(csv_path)) == {3, 7, 15}

    def test_arquivo_inexistente_retorna_conjunto_vazio_em_vez_de_quebrar(self, tmp_path):
        caminho_que_nao_existe = tmp_path / "nao_existe.csv"

        assert carregar_opt_out_ids(str(caminho_que_nao_existe)) == set()

    def test_csv_sem_coluna_user_id_levanta_erro_claro(self, tmp_path):
        csv_path = tmp_path / "opt_out.csv"
        csv_path.write_text("id_errado\n3\n7\n")

        with pytest.raises(ValueError, match="user_id"):
            carregar_opt_out_ids(str(csv_path))