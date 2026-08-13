from unittest.mock import patch

import pytest

from extract import buscar_todos_usuarios
from settings import Settings


def _settings(page_size=50):
    return Settings(
        api_url="https://users-api-python.onrender.com",
        api_username="admin",
        api_password="senha-fake",
        timeout_sec=20,
        saldo_limite_baixo=1000.0,
        saldo_limite_alto=20000.0,
        opt_out_path="data/opt_out.csv",
        audit_log_path="logs/audit_log.jsonl",
        report_path="report_etl.csv",
        page_size=page_size,
        gemini_api_key="fake-key",
        gemini_model="gemini-2.5-flash",
        icon_url="https://exemplo.com/icon.svg",
        wrap_news_width=75,
    )


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or []
        self.text = text

    def json(self):
        return self._payload


def _usuario(id_):
    return {"id": id_, "nome": f"Usuario {id_}", "conta": {"balanco": 100.0}, "news": []}


class TestPaginacao:
    @patch("extract.requests.get")
    def test_pagina_unica_menor_que_o_limite_para_apos_uma_chamada(self, mock_get):
        mock_get.return_value = _FakeResponse(200, [_usuario(1), _usuario(2)])

        resultado = buscar_todos_usuarios(_settings(page_size=50))

        assert len(resultado) == 2
        assert mock_get.call_count == 1

    @patch("extract.requests.get")
    def test_multiplas_paginas_sao_concatenadas_corretamente(self, mock_get):
        pagina_1 = [_usuario(i) for i in range(1, 3)]   # 2 itens, page_size=2 -> continua
        pagina_2 = [_usuario(i) for i in range(3, 5)]   # 2 itens -> continua
        pagina_3 = [_usuario(5)]                          # 1 item < 2 -> para
        mock_get.side_effect = [
            _FakeResponse(200, pagina_1),
            _FakeResponse(200, pagina_2),
            _FakeResponse(200, pagina_3),
        ]

        resultado = buscar_todos_usuarios(_settings(page_size=2))

        assert len(resultado) == 5
        assert [u["id"] for u in resultado] == [1, 2, 3, 4, 5]
        assert mock_get.call_count == 3

    @patch("extract.requests.get")
    def test_offset_avanca_corretamente_a_cada_pagina(self, mock_get):
        mock_get.side_effect = [
            _FakeResponse(200, [_usuario(1), _usuario(2)]),
            _FakeResponse(200, [_usuario(3)]),
        ]

        buscar_todos_usuarios(_settings(page_size=2))

        primeira_chamada_offset = mock_get.call_args_list[0].kwargs["params"]["offset"]
        segunda_chamada_offset = mock_get.call_args_list[1].kwargs["params"]["offset"]

        assert primeira_chamada_offset == 0
        assert segunda_chamada_offset == 2

    @patch("extract.requests.get")
    def test_base_vazia_retorna_lista_vazia_sem_erro(self, mock_get):
        mock_get.return_value = _FakeResponse(200, [])

        resultado = buscar_todos_usuarios(_settings())

        assert resultado == []
        assert mock_get.call_count == 1


class TestErroDeApi:
    @patch("extract.requests.get")
    def test_status_diferente_de_200_levanta_runtime_error_com_contexto(self, mock_get):
        mock_get.return_value = _FakeResponse(500, text="Internal Server Error")

        with pytest.raises(RuntimeError, match="500"):
            buscar_todos_usuarios(_settings())

    @patch("extract.requests.get")
    def test_erro_na_segunda_pagina_nao_perde_a_primeira_silenciosamente(self, mock_get):
        # a função levanta erro (não retorna parcial) -- comportamento
        # deliberado: dado parcial sem sinalização é pior que falha explícita
        mock_get.side_effect = [
            _FakeResponse(200, [_usuario(1), _usuario(2)]),
            _FakeResponse(503, text="Service Unavailable"),
        ]

        with pytest.raises(RuntimeError, match="503"):
            buscar_todos_usuarios(_settings(page_size=2))