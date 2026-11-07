"""
push.py - Web Push (VAPID): avisa o celular mesmo com o aplicativo fechado.

Como funciona
  1. A PWA pede permissão, cria uma "assinatura" no navegador e envia para a API (/api/push/assinaturas).
  2. A assinatura fica na tabela `assinatura_push`.
  3. Quando um alerta é gravado, `avisar()` manda uma mensagem para cada assinatura; o service worker
     do celular recebe e mostra a notificação.

Chaves VAPID: VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY no .env. VAPID_CONTATO precisa ser um e-mail ou URL
válidos (ex.: mailto:admin@example.com): a Apple recusa com 403 BadJwtToken se ele for inválido (ex.: ".local").
Cada tentativa de envio fica registrada na tabela envio_push (resultado OK ou FALHA). Gere com:
    python -m sentinela_api.push --gerar-chaves
O celular só aceita push em páginas HTTPS (localhost também vale, para testes no próprio PC).
"""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import time
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


MAX_ENVIOS_SIMULTANEOS = 8  # aparelhos avisados ao mesmo tempo
# Trecho da resposta do FCM quando a assinatura foi criada com OUTRA chave VAPID (ex.: depois de trocar as chaves).
_CHAVE_INCOMPATIVEL = "do not correspond"

TIMEOUT_ENVIO_S = 10  # limite de espera por tentativa de envio (conexão e resposta)

_TITULOS = {"QUEDA": "Queda detectada", "MOVIMENTO_ANOMALO": "Pessoa no chão"}


class ServicoPush:
    def __init__(self, banco: Banco, chave_publica: Optional[str] = None, chave_privada: Optional[str] = None,
                 contato: Optional[str] = None, enviar_fn=None):
        self.banco = banco
        self.chave_publica = chave_publica or os.getenv("VAPID_PUBLIC_KEY", "")
        self._chave_privada = chave_privada or os.getenv("VAPID_PRIVATE_KEY", "")
        self._contato = contato or os.getenv("VAPID_CONTATO", "mailto:admin@example.com")
        self._enviar = enviar_fn  # injetável nos testes
        self._espera_retentativa_s = 2.0

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
        alerta_id = alerta["id"] if isinstance(alerta["id"], int) else None
        assinaturas = self.banco.listar_assinaturas()
        if not assinaturas:
            return
        # Todos os aparelhos ao mesmo tempo: um aparelho lento ou com problema não atrasa os outros.
        with ThreadPoolExecutor(max_workers=min(MAX_ENVIOS_SIMULTANEOS, len(assinaturas))) as pool:
            for sub in assinaturas:
                pool.submit(self._enviar_uma, sub, mensagem, alerta_id)

    @staticmethod
    def _erro_passageiro(codigo: Optional[int]) -> bool:
        """Vale tentar de novo? Sim: sem resposta (queda de rede, tempo esgotado), 429 ou erro do servidor (5xx)."""
        return codigo is None or codigo == 429 or codigo >= 500

    def _enviar_uma(self, sub: Dict[str, Any], mensagem: str, alerta_id: Optional[int] = None) -> None:
        """Tenta enviar (com 1 nova tentativa só em erro passageiro) e registra o resultado em envio_push."""
        enviar = self._enviar
        if enviar is None:
            from pywebpush import webpush
            enviar = webpush
        codigo, detalhe = None, None
        for tentativa in (1, 2):
            try:
                enviar(subscription_info={"endpoint": sub["endpoint"],
                                          "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                       data=mensagem, vapid_private_key=self._chave_privada,
                       vapid_claims={"sub": self._contato}, ttl=3600,
                       timeout=TIMEOUT_ENVIO_S)  # sem isso, uma conexão que trava deixa o envio parado para sempre
                self._registrar(sub, alerta_id, "OK", None, None)
                return
            except Exception as erro:  # noqa: BLE001
                resposta = getattr(erro, "response", None)
                codigo = getattr(resposta, "status_code", None)
                detalhe = f"{type(erro).__name__}: {erro}"
                texto = str(getattr(resposta, "text", "") or "") + detalhe
                if codigo in (404, 410):  # o aparelho cancelou ou a assinatura expirou: não adianta insistir
                    self.banco.remover_assinatura(sub["endpoint"])
                    break
                if codigo == 403 and _CHAVE_INCOMPATIVEL in texto:
                    # Assinatura feita com outra chave VAPID: nunca mais funciona até o aparelho se cadastrar de novo.
                    self.banco.remover_assinatura(sub["endpoint"])
                    detalhe = "assinatura removida: criada com outra chave VAPID (o aparelho precisa ativar as notificações de novo)"
                    break
                if not self._erro_passageiro(codigo):
                    break  # 400/401/403... não melhoram sozinhos: tentar de novo só gasta tempo
                if tentativa == 1:
                    time.sleep(self._espera_retentativa_s)
        print(f"[Push] falha ao enviar ({codigo or 'erro'}): {detalhe}")
        self._registrar(sub, alerta_id, "FALHA", codigo, detalhe)

    def _registrar(self, sub: Dict[str, Any], alerta_id: Optional[int], resultado: str,
                   codigo: Optional[int], detalhe: Optional[str]) -> None:
        try:
            self.banco.registrar_envio_push(sub.get("id"), alerta_id, resultado, codigo, detalhe)
        except Exception as erro:  # noqa: BLE001 - registrar não pode derrubar o aviso
            print(f"[Push] não foi possível registrar o envio: {erro}")


if __name__ == "__main__":
    import sys
    if "--gerar-chaves" in sys.argv:
        for nome, valor in gerar_chaves().items():
            print(f"{nome}={valor}")
    else:
        print("Uso: python -m sentinela_api.push --gerar-chaves")
