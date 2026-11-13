"""
notificador_remoto.py - Avisa o serviço de WhatsApp (repositório sentinela_whatsapp, outro servidor)
que um alerta acabou de ser gravado.

    Sentinela grava alerta no PostgreSQL ──▶ POST {NOTIFICADOR_URL}/notificar  (Bearer NOTIFICADOR_TOKEN)
                                                    │
                                     notificador acorda, lê o alerta e os contatos no MESMO banco
                                     e envia o WhatsApp na hora

O aviso só acelera: se a rede falhar, o notificador encontra o alerta sozinho na próxima
verificação do banco (a cada poucos segundos). Por isso uma falha aqui só gera log, nunca trava a detecção.

Configuração (.env): NOTIFICADOR_URL=http://servidor-whatsapp:8100  e  NOTIFICADOR_TOKEN=<o mesmo NOTIF_TOKEN do notificador>
"""

import os
import threading
from typing import Any, Callable, Dict, Optional

import requests

TIMEOUT_S = 5


class NotificadorRemoto:
    def __init__(self, url: Optional[str] = None, token: Optional[str] = None,
                 enviar: Optional[Callable[..., Any]] = None):
        self.url = (url if url is not None else os.getenv("NOTIFICADOR_URL", "")).rstrip("/")
        self.token = token if token is not None else os.getenv("NOTIFICADOR_TOKEN", "")
        self._enviar = enviar or requests.post  # injetável nos testes

    @property
    def configurado(self) -> bool:
        return bool(self.url and self.token)

    def avisar(self, alerta: Dict[str, Any]) -> None:
        """Dispara em outra thread: a detecção de quedas nunca espera a rede."""
        if self.configurado:
            threading.Thread(target=self._post, args=(alerta["id"],), daemon=True).start()

    def _post(self, alerta_id: int) -> None:
        try:
            resposta = self._enviar(f"{self.url}/notificar", json={"alerta_id": alerta_id},
                                    headers={"Authorization": f"Bearer {self.token}"}, timeout=TIMEOUT_S)
            if resposta.status_code != 202:
                print(f"[WhatsApp] notificador respondeu {resposta.status_code} para o alerta {alerta_id}")
        except requests.RequestException as erro:
            print(f"[WhatsApp] notificador indisponível ({erro.__class__.__name__}); "
                  f"o alerta {alerta_id} será enviado na próxima verificação do banco")

    def avisar_texto(self, texto: str) -> None:
        """Aviso que não é alerta de queda (ex.: câmera sem sinal): POST /aviso no notificador, em segundo plano."""
        if self.configurado:
            threading.Thread(target=self._post_texto, args=(texto,), daemon=True).start()

    def _post_texto(self, texto: str) -> None:
        try:
            resposta = self._enviar(f"{self.url}/aviso", json={"texto": texto[:500]},
                                    headers={"Authorization": f"Bearer {self.token}"}, timeout=TIMEOUT_S)
            if resposta.status_code != 202:
                print(f"[WhatsApp] notificador respondeu {resposta.status_code} ao aviso")
        except requests.RequestException as erro:
            print(f"[WhatsApp] notificador indisponível para o aviso ({erro.__class__.__name__})")
