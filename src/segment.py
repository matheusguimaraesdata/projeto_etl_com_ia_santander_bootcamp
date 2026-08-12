"""
Segmentação de audiência para a campanha multi-segmento.

Regra de negócio:
    Base elegível = zero news (nunca recebeu comunicação da campanha)
                     E não está na lista de supressão (opt-out)

    Dentro da base elegível, cada usuário é classificado em UM segmento:
        - EDUCACAO_FINANCEIRA:      saldo < saldo_limite_baixo (inclui negativo)
        - INVESTIMENTOS_AVANCADOS:  saldo > saldo_limite_alto
        - (nenhum)                  saldo entre os dois limites — não é
                                     público de nenhuma das duas campanhas

Os limites são configuráveis e não podem se sobrepor: saldo_limite_baixo
precisa ser estritamente menor que saldo_limite_alto.

Separado do resto do pipeline de propósito: esta é a única parte que
representa uma decisão de negócio, então é a única que precisa de
cobertura de teste rigorosa e pode evoluir sem tocar em extração,
enriquecimento ou carga.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

import pandas as pd


@dataclass(frozen=True)
class SegmentacaoResultado:
    """Resultado da segmentação, com números para auditoria/observabilidade."""
    usuarios_educacao_financeira: List[Dict[str, Any]] = field(default_factory=list)
    usuarios_investimentos_avancados: List[Dict[str, Any]] = field(default_factory=list)
    total_avaliados: int = 0
    excluidos_por_news_existente: int = 0
    excluidos_por_supressao: int = 0
    excluidos_por_faixa_neutra: int = 0

    @property
    def total_educacao_financeira(self) -> int:
        return len(self.usuarios_educacao_financeira)

    @property
    def total_investimentos_avancados(self) -> int:
        return len(self.usuarios_investimentos_avancados)

    @property
    def total_elegiveis(self) -> int:
        return self.total_educacao_financeira + self.total_investimentos_avancados

    def resumo(self) -> str:
        return (
            f"Avaliados: {self.total_avaliados} | "
            f"Educação financeira: {self.total_educacao_financeira} | "
            f"Investimentos avançados: {self.total_investimentos_avancados} | "
            f"Excluídos (faixa neutra, nenhuma campanha se aplica): {self.excluidos_por_faixa_neutra} | "
            f"Excluídos (já receberam news): {self.excluidos_por_news_existente} | "
            f"Excluídos (lista de supressão): {self.excluidos_por_supressao}"
        )


def _usuarios_para_dataframe(usuarios: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Achata a lista de usuários (formato aninhado da API) em um DataFrame
    plano, só com as colunas que a regra de negócio precisa.
    """
    linhas = []
    for u in usuarios:
        conta = u.get("conta") or {}
        linhas.append(
            {
                "id": u["id"],
                "balanco": float(conta.get("balanco", 0.0) or 0.0),
                "qtd_news": len(u.get("news") or []),
            }
        )
    return pd.DataFrame(linhas, columns=["id", "balanco", "qtd_news"])


def selecionar_audiencia(
    usuarios: List[Dict[str, Any]],
    opt_out_ids: Set[int],
    saldo_limite_baixo: float,
    saldo_limite_alto: float,
) -> SegmentacaoResultado:
    """
    Aplica a regra de negócio multi-segmento sobre a lista completa de
    usuários e retorna, separadamente, quem é elegível para cada campanha,
    junto com números de auditoria.

    Args:
        usuarios: lista de usuários no formato retornado pela API
            (cada item precisa ter "id" e pode ter "conta" e "news").
        opt_out_ids: IDs que pediram para não receber comunicação.
        saldo_limite_baixo: abaixo disso, entra na campanha de educação
            financeira (aceita valores negativos normalmente).
        saldo_limite_alto: acima disso, entra na campanha de investimentos
            avançados.

    Raises:
        ValueError: se saldo_limite_baixo não for estritamente menor que
            saldo_limite_alto — limites invertidos ou iguais indicam erro
            de configuração, não uma regra de negócio válida.
    """
    if saldo_limite_baixo >= saldo_limite_alto:
        raise ValueError(
            "saldo_limite_baixo precisa ser menor que saldo_limite_alto "
            f"(recebido: baixo={saldo_limite_baixo}, alto={saldo_limite_alto})"
        )

    if not usuarios:
        return SegmentacaoResultado(total_avaliados=0)

    df = _usuarios_para_dataframe(usuarios)
    total_avaliados = len(df)

    mascara_sem_news = df["qtd_news"] == 0
    mascara_nao_suprimido = ~df["id"].isin(opt_out_ids)
    pool_elegivel = mascara_sem_news & mascara_nao_suprimido

    excluidos_por_news_existente = int((~mascara_sem_news).sum())
    excluidos_por_supressao = int((mascara_sem_news & ~mascara_nao_suprimido).sum())

    mascara_educacao = pool_elegivel & (df["balanco"] < saldo_limite_baixo)
    mascara_investimento = pool_elegivel & (df["balanco"] > saldo_limite_alto)
    mascara_neutro = pool_elegivel & ~mascara_educacao & ~mascara_investimento

    ids_educacao = set(df.loc[mascara_educacao, "id"].tolist())
    ids_investimento = set(df.loc[mascara_investimento, "id"].tolist())

    return SegmentacaoResultado(
        usuarios_educacao_financeira=[u for u in usuarios if u["id"] in ids_educacao],
        usuarios_investimentos_avancados=[u for u in usuarios if u["id"] in ids_investimento],
        total_avaliados=total_avaliados,
        excluidos_por_news_existente=excluidos_por_news_existente,
        excluidos_por_supressao=excluidos_por_supressao,
        excluidos_por_faixa_neutra=int(mascara_neutro.sum()),
    )


def carregar_opt_out_ids(csv_path: str) -> Set[int]:
    """
    Lê a lista de supressão (opt-out.csv, coluna 'user_id').
    Arquivo ausente ou vazio não é erro — significa lista de supressão vazia,
    não interrupção do pipeline.
    """
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        return set()

    if "user_id" not in df.columns:
        raise ValueError(
            f"opt_out.csv precisa ter coluna 'user_id'. Colunas encontradas: {list(df.columns)}"
        )

    return set(df["user_id"].dropna().astype(int).tolist())