"""
manutencao.py - Rotina diária: retenção de dados (LGPD) e limpeza.

Sem ela, fotos de residentes, detalhes dos alertas e o histórico de envios de push cresciam para sempre.
Uma vez por dia (e logo ao iniciar):
  - apaga alertas JÁ TRATADOS com mais de RETENCAO_DIAS dias (padrão 90), os eventos e as FOTOS deles;
    alertas PENDENTES nunca são apagados;
  - apaga o histórico de envios de push mais antigo que isso;
  - apaga sessões de login vencidas.
RETENCAO_DIAS=0 desliga a retenção (guarda tudo).
"""

import logging
import os
import threading
from typing import List, Optional

log = logging.getLogger("sentinela.manutencao")

UM_DIA_S = 24 * 3600


def apagar_fotos(caminhos: List[str], pasta_fotos: str) -> int:
    """Apaga só arquivos que estão DENTRO da pasta de fotos (um caminho estranho no banco não apaga nada fora dela)."""
    pasta = os.path.realpath(pasta_fotos)
    apagadas = 0
    for caminho in caminhos:
        real = os.path.realpath(caminho)
        if os.path.commonpath([pasta, real]) == pasta and os.path.isfile(real):
            try:
                os.remove(real)
                apagadas += 1
            except OSError:
                pass
    return apagadas


def executar(banco, pasta_fotos: str, dias: int) -> dict:
    """Uma rodada de manutenção. Devolve o que foi feito (para log e testes)."""
    banco.limpar_sessoes_expiradas()
    if dias <= 0:
        return {"alertas": 0, "fotos": 0}
    fotos = banco.apagar_historico_antigo(dias)
    apagadas = apagar_fotos(fotos, pasta_fotos)
    if fotos:
        log.info("Retenção: %d alerta(s) tratado(s) com mais de %d dias apagado(s), %d foto(s) removida(s)",
                 len(fotos), dias, apagadas)
    return {"alertas": len(fotos), "fotos": apagadas}


class RotinaDiaria:
    def __init__(self, banco, pasta_fotos: str, dias: Optional[int] = None, intervalo_s: float = UM_DIA_S):
        self.banco = banco
        self.pasta_fotos = pasta_fotos
        self.dias = dias if dias is not None else int(os.getenv("RETENCAO_DIAS", "90"))
        self.intervalo_s = intervalo_s
        self._parar = threading.Event()

    def iniciar(self) -> None:
        threading.Thread(target=self._laco, name="manutencao", daemon=True).start()

    def parar(self) -> None:
        self._parar.set()

    def _laco(self) -> None:
        while True:
            try:
                executar(self.banco, self.pasta_fotos, self.dias)
            except Exception:  # noqa: BLE001 - banco fora do ar: tenta no próximo dia
                log.exception("Falha na manutenção diária")
            if self._parar.wait(self.intervalo_s):
                return
