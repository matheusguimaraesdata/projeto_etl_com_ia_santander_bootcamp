"""
Extração de dados a partir da users-api-python.

A API não expõe contagem total de registros (GET /usuario retorna uma
lista simples, sem wrapper com "total"). Por isso a paginação aqui segue
a única estratégia confiável possível: continuar pedindo páginas até que
uma página volte com menos itens do que o limite pedido — sinal de que
chegamos ao fim.

A leitura da lista de supressão (opt_out.csv) vive em segment.py, não
aqui — decisão deliberada: quem consome essa lista para decidir exclusão
é a regra de negócio, então ela é dona do próprio dado de entrada.
"""
from typing import Any, Dict, List

import requests

from settings import Settings


def buscar_todos_usuarios(settings: Settings) -> List[Dict[str, Any]]:
    """
    Busca a base inteira de usuários na API, paginando automaticamente.

    Raises:
        RuntimeError: se qualquer página retornar status diferente de 200.
            Não faz retry aqui de propósito — essa é uma responsabilidade
            que entra numa passada futura de robustez (backoff/retry),
            não desta função.
    """
    usuarios: List[Dict[str, Any]] = []
    offset = 0

    while True:
        resp = requests.get(
            f"{settings.api_url}/usuario",
            params={"offset": offset, "limit": settings.page_size},
            timeout=settings.timeout_sec,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"GET /usuario falhou (offset={offset}, limit={settings.page_size}): "
                f"{resp.status_code} | {resp.text[:200]}"
            )

        pagina = resp.json()
        usuarios.extend(pagina)

        if len(pagina) < settings.page_size:
            break

        offset += settings.page_size

    return usuarios