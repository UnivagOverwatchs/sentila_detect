"""
vigia.py - Avisa quando uma câmera para de mandar sinal (modo painel).

Por que: antes o painel só mostrava "offline". De madrugada ninguém olha o painel; uma câmera desligada,
sem internet ou com o agente travado deixava o residente SEM proteção sem que ninguém soubesse.

Como funciona: a cada `intervalo_s` confere as câmeras ATIVAS que já mandaram sinal alguma vez. Se uma ficar
mais de CAMERA_OFFLINE_AVISO_S (padrão 300 s = 5 min) sem notícias, avisa por push e WhatsApp UMA vez; quando
volta, avisa que voltou. Câmeras desligadas no painel (interruptor) não geram aviso.
"""

import logging
import os
import threading
from typing import Callable, Dict, Optional, Set

log = logging.getLogger("sentinela.vigia")


class VigiaCameras:
    def __init__(self, banco, servico, push=None, notificador_remoto=None,
                 limite_s: Optional[float] = None, intervalo_s: float = 30.0):
        self.banco = banco
        self.servico = servico
        self.push = push
        self.notificador_remoto = notificador_remoto
        self.limite_s = limite_s if limite_s is not None else float(os.getenv("CAMERA_OFFLINE_AVISO_S", "300"))
        self.intervalo_s = intervalo_s
        self.sem_sinal: Set[int] = set()  # câmeras já avisadas como sem sinal (não repete o aviso)
        self._parar = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def verificar(self) -> Dict[str, list]:
        """Uma verificação. Devolve quais câmeras caíram e voltaram nesta rodada (útil nos testes)."""
        vistos = self.servico.vistos_ha_s()
        caiu, voltou = [], []
        for camera in self.banco.listar_cameras():
            cid = camera["id"]
            if not camera["ativa"] or cid not in vistos:
                self.sem_sinal.discard(cid)  # desligada no painel ou nunca conectou: não é falha
                continue
            fora = vistos[cid] > self.limite_s
            if fora and cid not in self.sem_sinal:
                self.sem_sinal.add(cid)
                caiu.append(camera)
                self._avisar(f"Câmera sem sinal: {camera['nome']}",
                             f"Sem notícias há {int(vistos[cid] // 60)} min. O ambiente NÃO está sendo monitorado.",
                             f"camera-{cid}")
            elif not fora and cid in self.sem_sinal:
                self.sem_sinal.discard(cid)
                voltou.append(camera)
                self._avisar(f"Câmera voltou: {camera['nome']}", "O monitoramento foi retomado.", f"camera-{cid}")
        return {"caiu": caiu, "voltou": voltou}

    def _avisar(self, titulo: str, corpo: str, tag: str) -> None:
        log.warning("%s - %s", titulo, corpo)
        if self.push is not None and hasattr(self.push, "avisar_texto"):
            self.push.avisar_texto(titulo, corpo, tag)
        if self.notificador_remoto is not None and hasattr(self.notificador_remoto, "avisar_texto"):
            self.notificador_remoto.avisar_texto(f"⚠️ SENTINELA — {titulo}\n{corpo}")

    def iniciar(self) -> None:
        if not hasattr(self.servico, "vistos_ha_s"):
            return  # só faz sentido no modo painel (câmeras remotas)
        self._thread = threading.Thread(target=self._laco, name="vigia-cameras", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()

    def _laco(self) -> None:
        while not self._parar.wait(self.intervalo_s):
            try:
                self.verificar()
            except Exception:  # noqa: BLE001 - banco fora do ar etc.: tenta na próxima rodada
                log.exception("Falha ao verificar as câmeras")
