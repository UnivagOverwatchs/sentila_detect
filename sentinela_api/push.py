"""
push.py - Web Push (VAPID): avisa o celular mesmo com o aplicativo fechado.

Como funciona
  1. A PWA pede permissão, cria uma "assinatura" no navegador e envia para a API (/api/push/assinaturas).
  2. A assinatura fica na tabela `assinatura_push`.
  3. Quando um alerta é gravado, `avisar()` manda uma mensagem para cada assinatura; o service worker
     do celular recebe e mostra a notificação.

Chaves VAPID: VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY no .env. Gere com:
    python -m sentinela_api.push --gerar-chaves
O celular só aceita push em páginas HTTPS (localhost também vale, para testes no próprio PC).
"""

import base64
import json
import os
import threading
from typing import Any, Dict, Optional

from .banco import Banco


def _b64url(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode("ascii")


def gerar_chaves() -> Dict[str, str]:
    """Cria um par de chaves VAPID (formato base64url, o que o navegador e o pywebpush esperam)."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()
    privada = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    publica = vapid.public_key.public_bytes(serialization.Encoding.X962,
                                            serialization.PublicFormat.UncompressedPoint)
    return {"VAPID_PUBLIC_KEY": _b64url(publica), "VAPID_PRIVATE_KEY": _b64url(privada)}


_TITULOS = {"QUEDA": "Queda detectada", "MOVIMENTO_ANOMALO": "Pessoa no chão"}


class ServicoPush:
    def __init__(self, banco: Banco, chave_publica: Optional[str] = None, chave_privada: Optional[str] = None,
                 contato: Optional[str] = None, enviar_fn=None):
        self.banco = banco
        self.chave_publica = chave_publica or os.getenv("VAPID_PUBLIC_KEY", "")
        self._chave_privada = chave_privada or os.getenv("VAPID_PRIVATE_KEY", "")
        self._contato = contato or os.getenv("VAPID_CONTATO", "mailto:admin@sentinela.local")
        self._enviar = enviar_fn  # injetável nos testes

    @property
    def configurado(self) -> bool:
        return bool(self.chave_publica and self._chave_privada)

    def avisar(self, alerta: Dict[str, Any]) -> None:
        """Dispara o envio em uma thread para não travar o loop de vídeo."""
        if not self.configurado:
            return
        threading.Thread(target=self._enviar_para_todos, args=(alerta,), daemon=True).start()

    def _enviar_para_todos(self, alerta: Dict[str, Any]) -> None:
        mensagem = json.dumps({
            "titulo": _TITULOS.get(alerta["tipo"], "Alerta"),
            "corpo": f"{alerta['camera_nome']} · agora",
            "alerta_id": alerta["id"],
        })
        for sub in self.banco.listar_assinaturas():
            self._enviar_uma(sub, mensagem)

    def _enviar_uma(self, sub: Dict[str, Any], mensagem: str) -> None:
        enviar = self._enviar
        if enviar is None:
            from pywebpush import WebPushException, webpush
            enviar = webpush
        try:
            enviar(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                   data=mensagem, vapid_private_key=self._chave_privada,
                   vapid_claims={"sub": self._contato}, ttl=3600)
        except Exception as erro:  # noqa: BLE001
            codigo = getattr(getattr(erro, "response", None), "status_code", None)
            if codigo in (404, 410):  # o aparelho cancelou ou a assinatura expirou
                self.banco.remover_assinatura(sub["endpoint"])
            print(f"[Push] falha ao enviar ({codigo or type(erro).__name__}): {erro}")


if __name__ == "__main__":
    import sys
    if "--gerar-chaves" in sys.argv:
        for nome, valor in gerar_chaves().items():
            print(f"{nome}={valor}")
    else:
        print("Uso: python -m sentinela_api.push --gerar-chaves")
