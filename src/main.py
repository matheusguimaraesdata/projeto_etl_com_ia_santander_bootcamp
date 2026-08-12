"""
Orquestração do pipeline: Extract -> Segment -> Enrich -> Load.

Cada estágio já é testado isoladamente nos próprios módulos. Este arquivo
não tem lógica de negócio nenhuma — só decide a ordem de execução, corta
caminho cedo quando não há ninguém elegível (evita autenticar na API e
instanciar cliente Gemini à toa) e consolida um relatório da execução.
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import extract
import segment
import enrich
import load as load_module  # nome explícito evita confundir com o verbo "carregar"
from settings import Settings, load_settings


def _salvar_relatorio(
    settings: Settings,
    resultado_segmentacao: segment.SegmentacaoResultado,
    resultado_carga: Optional[load_module.LoadResultado],
) -> None:
    """
    Acrescenta uma linha ao CSV de relatório por execução — histórico de
    todas as rodadas do pipeline ao longo do tempo, não só a última.
    """
    linha = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_avaliados": resultado_segmentacao.total_avaliados,
        "educacao_financeira": resultado_segmentacao.total_educacao_financeira,
        "investimentos_avancados": resultado_segmentacao.total_investimentos_avancados,
        "excluidos_faixa_neutra": resultado_segmentacao.excluidos_por_faixa_neutra,
        "excluidos_news_existente": resultado_segmentacao.excluidos_por_news_existente,
        "excluidos_supressao": resultado_segmentacao.excluidos_por_supressao,
        "gravados_sucesso": resultado_carga.sucesso if resultado_carga else 0,
        "gravados_falha": resultado_carga.falha if resultado_carga else 0,
    }

    caminho = Path(settings.report_path)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    arquivo_ja_existe = caminho.exists()

    with open(caminho, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=linha.keys())
        if not arquivo_ja_existe:
            writer.writeheader()
        writer.writerow(linha)


def executar_pipeline(settings: Optional[Settings] = None) -> None:
    """
    Executa uma rodada completa do pipeline.

    Args:
        settings: injeção opcional (usada nos testes). Em execução real,
            carrega do .env normalmente.
    """
    settings = settings or load_settings()

    print(f"[INFO] Iniciando pipeline contra {settings.api_url}")

    usuarios = extract.buscar_todos_usuarios(settings)
    print(f"[INFO] {len(usuarios)} usuários extraídos da API")

    opt_out_ids = segment.carregar_opt_out_ids(settings.opt_out_path)
    print(f"[INFO] {len(opt_out_ids)} IDs na lista de supressão")

    resultado_segmentacao = segment.selecionar_audiencia(
        usuarios, opt_out_ids, settings.saldo_limite_baixo, settings.saldo_limite_alto
    )
    print(f"[INFO] {resultado_segmentacao.resumo()}")

    if resultado_segmentacao.total_elegiveis == 0:
        print("[INFO] Nenhum usuário elegível para nenhuma campanha nesta rodada. Encerrando sem chamar Gemini/API de escrita.")
        _salvar_relatorio(settings, resultado_segmentacao, resultado_carga=None)
        return

    client = enrich.montar_cliente_gemini(settings)
    usuarios_enriquecidos = enrich.enriquecer_usuarios(
        client,
        settings.gemini_model,
        {
            enrich.SEGMENTO_EDUCACAO_FINANCEIRA: resultado_segmentacao.usuarios_educacao_financeira,
            enrich.SEGMENTO_INVESTIMENTOS_AVANCADOS: resultado_segmentacao.usuarios_investimentos_avancados,
        },
        settings.icon_url,
    )
    print(f"[INFO] {len(usuarios_enriquecidos)} mensagens geradas via Gemini")

    resultado_carga = load_module.carregar_usuarios(settings, usuarios_enriquecidos)
    print(f"[INFO] {resultado_carga.resumo()}")

    _salvar_relatorio(settings, resultado_segmentacao, resultado_carga)
    print(f"[INFO] Relatório da execução salvo em {settings.report_path}")
    print(f"[INFO] Log de auditoria por usuário em {settings.audit_log_path}")


if __name__ == "__main__":
    try:
        executar_pipeline()
    except Exception as e:
        print(f"[ERROR] Pipeline abortado: {e}")
        sys.exit(1)