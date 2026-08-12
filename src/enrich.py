"""
Enriquecimento via IA generativa (Google Gemini) — mensagem personalizada
por segmento de campanha.

Cada segmento tem seu próprio prompt e sua própria mensagem de fallback.
Fallback nunca é genérico: se fosse a mesma frase pros dois segmentos, uma
falha do Gemini faria todo mundo receber a mesma comunicação, o que
contradiz o próprio propósito da segmentação.
"""
import re
import textwrap
from typing import Any, Dict, List

from google import genai
from google.genai import errors

from settings import Settings

SEGMENTO_EDUCACAO_FINANCEIRA = "educacao_financeira"
SEGMENTO_INVESTIMENTOS_AVANCADOS = "investimentos_avancados"

_MAX_CARACTERES_MENSAGEM = 100

_PROMPTS = {
    SEGMENTO_EDUCACAO_FINANCEIRA: (
        "Você é um especialista em educação financeira de um banco.\n"
        "Crie uma mensagem breve e acolhedora para {nome}, incentivando o "
        "controle do orçamento e a criação de uma reserva de emergência "
        f"(máximo de {_MAX_CARACTERES_MENSAGEM} caracteres)."
    ),
    SEGMENTO_INVESTIMENTOS_AVANCADOS: (
        "Você é um especialista em investimentos de um banco.\n"
        "Crie uma mensagem breve para {nome} sobre oportunidades de "
        "investimento avançado, como renda variável ou fundos multimercado "
        f"(máximo de {_MAX_CARACTERES_MENSAGEM} caracteres)."
    ),
}

_FALLBACKS = {
    SEGMENTO_EDUCACAO_FINANCEIRA: (
        "{nome}, organizar o orçamento hoje constrói sua segurança financeira amanhã."
    ),
    SEGMENTO_INVESTIMENTOS_AVANCADOS: (
        "{nome}, diversificar investimentos pode potencializar seus resultados no longo prazo."
    ),
}


def _clean_text(text: str) -> str:
    """Remove formatação/markdown simples que pode confundir leigos."""
    text = (text or "").strip()
    for marcador in ("**", "__", "`", "*"):
        text = text.replace(marcador, "")
    return re.sub(r"\s+", " ", text).strip()


def _next_news_id(usuario: Dict[str, Any]) -> int:
    news_list = usuario.get("news") or []
    if not news_list:
        return 1
    return max(int(n.get("id", 0)) for n in news_list) + 1


def montar_cliente_gemini(settings: Settings) -> genai.Client:
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY não configurada. Defina no .env.")
    return genai.Client(api_key=settings.gemini_api_key)


def gerar_mensagem(
    client: genai.Client, model: str, usuario: Dict[str, Any], segmento: str
) -> str:
    """
    Gera a mensagem personalizada para um usuário em um segmento específico.
    Nunca levanta exceção: se o Gemini falhar por qualquer motivo, retorna
    o fallback do próprio segmento em vez de derrubar o pipeline inteiro.
    """
    if segmento not in _PROMPTS:
        raise ValueError(f"Segmento desconhecido: {segmento!r}")

    nome = usuario.get("nome", "Cliente")
    prompt = _PROMPTS[segmento].format(nome=nome)
    fallback = _clean_text(_FALLBACKS[segmento].format(nome=nome))[:_MAX_CARACTERES_MENSAGEM]

    try:
        response = client.models.generate_content(model=model, contents=prompt)
        texto = _clean_text(getattr(response, "text", "") or "")
        return texto[:_MAX_CARACTERES_MENSAGEM] if texto else fallback
    except errors.APIError:
        return fallback
    except Exception:
        return fallback


def enriquecer_usuarios(
    client: genai.Client,
    model: str,
    usuarios_por_segmento: Dict[str, List[Dict[str, Any]]],
    icon_url: str,
) -> List[Dict[str, Any]]:
    """
    Enriquece todos os usuários de todos os segmentos com uma news
    personalizada. Cada usuário retornado carrega, além dos campos normais
    da API, duas chaves de metadado do pipeline (prefixadas com "_" pra
    deixar claro que não fazem parte do schema da API): qual segmento
    recebeu e qual foi a mensagem enviada — é o que alimenta o log de
    auditoria no próximo estágio.
    """
    enriquecidos: List[Dict[str, Any]] = []

    for segmento, usuarios in usuarios_por_segmento.items():
        for usuario in usuarios:
            mensagem = gerar_mensagem(client, model, usuario, segmento)

            usuario = dict(usuario)  # não muta a entrada original
            usuario["news"] = list(usuario.get("news") or [])
            usuario["news"].append(
                {"id": _next_news_id(usuario), "icone": icon_url, "descricao": mensagem}
            )
            usuario["_campanha_segmento"] = segmento
            usuario["_campanha_mensagem"] = mensagem

            enriquecidos.append(usuario)

    return enriquecidos