"""
Carga dos resultados de volta na users-api-python, com auditoria.

Duas decisões deliberadas, diferentes do etl.py original:

1. PATCH em vez de PUT — o endpoint de update completo (PUT) exige o
   objeto inteiro (nome, conta, cartão, recursos, news). Como só estamos
   adicionando uma news, PATCH é o verbo correto: manda só o campo que
   mudou, sem risco de sobrescrever dado que o pipeline nem deveria tocar.

2. Falha em UM usuário não derruba os demais. O laço continua, registra
   sucesso/falha por usuário no log de auditoria, e o retorno final deixa
   claro quantos falharam — quem rodar o pipeline decide o que fazer com
   isso, o pipeline não decide por conta própria abortar tudo.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests

from settings import Settings


@dataclass(frozen=True)
class LoadResultado:
    total: int
    sucesso: int
    falha: int

    def resumo(self) -> str:
        return f"Gravados: {self.sucesso}/{self.total} | Falhas: {self.falha}"


def autenticar(settings: Settings) -> str:
    """
    Faz login na API (OAuth2 password flow) e retorna o token JWT.

    Raises:
        RuntimeError: credenciais inválidas, API fora do ar, ou resposta
            sem o campo access_token esperado.
    """
    resp = requests.post(
        f"{settings.api_url}/auth/login",
        data={"username": settings.api_username, "password": settings.api_password},
        timeout=settings.timeout_sec,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Falha na autenticação em {settings.api_url}/auth/login: "
            f"{resp.status_code} | {resp.text[:200]}"
        )

    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("Login retornou 200 mas a resposta não contém 'access_token'.")

    return token


def atualizar_usuario(settings: Settings, token: str, usuario: Dict[str, Any]) -> bool:
    """
    Grava a news do usuário via PATCH (atualização parcial).
    Retorna True/False em vez de levantar exceção — a decisão de parar
    ou continuar o lote é de quem chama, não desta função.
    """
    resp = requests.patch(
        f"{settings.api_url}/usuario/{usuario['id']}",
        json={"news": usuario.get("news", [])},
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.timeout_sec,
    )
    return resp.status_code == 200


def registrar_auditoria(usuario: Dict[str, Any], sucesso: bool, audit_log_path: str) -> None:
    """Grava uma linha JSONL por usuário processado — quem, quando, qual segmento, qual mensagem, se deu certo."""
    Path(audit_log_path).parent.mkdir(parents=True, exist_ok=True)

    entrada = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "usuario_id": usuario.get("id"),
        "nome": usuario.get("nome"),
        "segmento": usuario.get("_campanha_segmento"),
        "mensagem": usuario.get("_campanha_mensagem"),
        "sucesso": sucesso,
    }

    with open(audit_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False) + "\n")


def carregar_usuarios(settings: Settings, usuarios: List[Dict[str, Any]]) -> LoadResultado:
    """
    Autentica uma vez e grava todos os usuários enriquecidos, auditando
    cada tentativa. Lista vazia não autentica — evita chamada de login
    desnecessária quando não há nada pra gravar.
    """
    if not usuarios:
        return LoadResultado(total=0, sucesso=0, falha=0)

    token = autenticar(settings)

    sucesso = 0
    falha = 0
    for usuario in usuarios:
        ok = atualizar_usuario(settings, token, usuario)
        registrar_auditoria(usuario, ok, settings.audit_log_path)
        if ok:
            sucesso += 1
        else:
            falha += 1

    return LoadResultado(total=len(usuarios), sucesso=sucesso, falha=falha)