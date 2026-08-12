"""
Configuração centralizada do pipeline.

Tudo que o pipeline precisa pra rodar vem de uma única fonte, carregada uma
vez em Settings (dataclass frozen). Nenhum módulo (extract/segment/enrich/
load) lê variável de ambiente diretamente — todos recebem Settings já
pronto. Isso evita que uma parte do pipeline leia uma configuração
inconsistente com outra durante a mesma execução.
"""
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    # API (users-api-python)
    api_url: str
    api_username: str
    api_password: str
    timeout_sec: int

    # Regra de negócio (segmentação multi-segmento)
    saldo_limite_baixo: float
    saldo_limite_alto: float

    # Arquivos de entrada/saída
    opt_out_path: str
    audit_log_path: str
    report_path: str

    # Paginação da API na extração
    page_size: int

    # Enriquecimento via Gemini
    gemini_api_key: Optional[str]
    gemini_model: str
    icon_url: str

    # Exibição no terminal
    wrap_news_width: int


def load_settings() -> Settings:
    load_dotenv()

    api_url = os.getenv("API_URL")
    if not api_url:
        # Sem default proposital: o antigo default apontava para a URL do
        # Railway, que não está mais no ar. Preferível falhar cedo e claro
        # a rodar o pipeline inteiro contra uma URL morta.
        raise ValueError(
            "API_URL não configurada. Defina no .env (URL da users-api-python na Render)."
        )
    api_url = api_url.rstrip("/")

    api_username = os.getenv("API_USERNAME")
    api_password = os.getenv("API_PASSWORD")
    if not api_username or not api_password:
        raise ValueError(
            "API_USERNAME e API_PASSWORD não configuradas. "
            "São as credenciais que o pipeline usa para autenticar na users-api-python "
            "e gravar as news (endpoints de escrita exigem login)."
        )

    saldo_limite_baixo = float(os.getenv("SALDO_LIMITE_BAIXO", "1000"))
    saldo_limite_alto = float(os.getenv("SALDO_LIMITE_ALTO", "20000"))
    if saldo_limite_baixo >= saldo_limite_alto:
        raise ValueError(
            "SALDO_LIMITE_BAIXO precisa ser menor que SALDO_LIMITE_ALTO "
            f"(recebido: baixo={saldo_limite_baixo}, alto={saldo_limite_alto})"
        )

    return Settings(
        api_url=api_url,
        api_username=api_username,
        api_password=api_password,
        timeout_sec=int(os.getenv("TIMEOUT_SEC", "20")),
        saldo_limite_baixo=saldo_limite_baixo,
        saldo_limite_alto=saldo_limite_alto,
        opt_out_path=os.getenv("OPT_OUT_PATH", "data/opt_out.csv"),
        audit_log_path=os.getenv("AUDIT_LOG_PATH", "logs/audit_log.jsonl"),
        report_path=os.getenv("REPORT_PATH", "report_etl.csv"),
        page_size=int(os.getenv("PAGE_SIZE", "50")),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        icon_url=os.getenv(
            "ICON_URL",
            "https://digitalinnovationone.github.io/santander-dev-week-2023-api/icons/credit.svg",
        ),
        wrap_news_width=int(os.getenv("WRAP_NEWS_WIDTH", "75")),
    )