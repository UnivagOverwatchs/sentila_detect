"""
registro.py - Configuração única dos logs (servidor e agente).

Antes as mensagens saíam com print(), sem horário nem gravidade: numa investigação na VPS
(`docker logs sentinela-painel`) não dava para saber QUANDO algo falhou. Agora cada linha tem
data/hora, nível (INFO, WARNING, ERROR) e a parte do sistema que falou.

    LOG_NIVEL=DEBUG|INFO|WARNING|ERROR   (padrão INFO)
"""

import logging
import os


def configurar_logs() -> None:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_NIVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
