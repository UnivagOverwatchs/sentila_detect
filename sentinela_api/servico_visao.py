"""
servico_visao.py - Roda a detecção de quedas em uma thread e expõe o resultado para a API.

É o mesmo pipeline do main_pose.py (captura -> pose -> lógica de queda -> desenho),
mas em vez de abrir uma janela do OpenCV ele:
  - guarda o último quadro anotado em JPEG (a API transmite como vídeo MJPEG);
  - grava cada alerta no banco (a PWA recebe pelo WebSocket);
  - mantém um resumo de status (FPS, pessoas em cena, estado geral).

Captura e estimador são INJETÁVEIS (parâmetros criar_captura/criar_estimador):
nos testes trocamos por versões falsas, sem câmera nem MediaPipe.
"""

import threading
import time
from typing import Any, Callable, Dict, Optional

import cv2
import numpy as np

from sentinela_pose.alertas import NotificadorAlertas
from sentinela_pose.config import ConfigPose, ConfigQueda
from sentinela_pose.fall_detector import DetectorQueda, Estado

from .banco import Banco

LARGURA, ALTURA = 640, 360
QUALIDADE_JPEG = 75          # equilíbrio entre nitidez e banda no Wi-Fi da instituição
CAMERA_OFFLINE_APOS_S = 3.0  # sem quadros por esse tempo = câmera offline


def _criar_captura_padrao(fonte: str):
    # Import tardio: reaproveita a classe já testada do main_pose.py sem duplicar código.
    from main_pose import CapturaVideo
    return CapturaVideo(fonte)


def _criar_estimador_padrao(cfg_pose: ConfigPose):
    from sentinela_pose.pose_estimator import EstimadorPose
    return EstimadorPose(cfg_pose)


def _desenhar_padrao(quadro, pessoas, fps):
    from main_pose import desenhar
    return desenhar(quadro, pessoas, fps)


def quadro_mensagem(texto: str) -> np.ndarray:
    """Quadro escuro com uma mensagem centralizada (câmera pausada/offline)."""
    tela = np.full((ALTURA, LARGURA, 3), (34, 23, 15), dtype=np.uint8)  # mesmo tom escuro da interface
    (largura_txt, _), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.putText(tela, texto, ((LARGURA - largura_txt) // 2, ALTURA // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
    return tela


class ServicoVisao:
    """Thread de visão. Uso: servico.iniciar() ... servico.parar()."""

    def __init__(self, banco: Banco, camera: Dict[str, Any], fonte: str,
                 cfg_queda: Optional[ConfigQueda] = None, cfg_pose: Optional[ConfigPose] = None,
                 criar_captura: Callable = _criar_captura_padrao,
                 criar_estimador: Callable = _criar_estimador_padrao,
                 desenhar: Callable = _desenhar_padrao,
                 notificador: Optional[NotificadorAlertas] = None):
        self.banco = banco
        self.camera = camera
        self.fonte = fonte
        self.cfg_queda = cfg_queda or ConfigQueda()
        self.cfg_pose = cfg_pose or ConfigPose()
        self._criar_captura = criar_captura
        self._criar_estimador = criar_estimador
        self._desenhar = desenhar
        self.notificador = notificador or NotificadorAlertas()

        self.ativa = bool(camera.get("ativa", True))  # alterado pela tela de Configurações
        self._rodando = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._jpeg: bytes = self._codificar(quadro_mensagem("Iniciando camera..."))
        self._status: Dict[str, Any] = {"fps": 0.0, "pessoas": 0, "estado": "normal",
                                        "camera_online": False, "erro": None}
        self._ultimo_quadro_em = 0.0

    # ------------------------------------------------------------ ciclo de vida
    def iniciar(self) -> None:
        self._rodando = True
        self._thread = threading.Thread(target=self._loop_seguro, name="servico-visao", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        """Pode ser chamado mais de uma vez (Ctrl+C e bloco finally)."""
        self._rodando = False
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    # ------------------------------------------------------------ leitura pela API
    def jpeg_atual(self) -> bytes:
        with self._lock:
            return self._jpeg

    def status(self) -> Dict[str, Any]:
        with self._lock:
            status = dict(self._status)
        status["camera_online"] = (time.time() - self._ultimo_quadro_em) < CAMERA_OFFLINE_APOS_S
        status["camera_ativa"] = self.ativa
        status["camera_id"] = self.camera["id"]  # a PWA usa para mostrar o nome da câmera certa
        return status

    # ------------------------------------------------------------ loop interno
    @staticmethod
    def _codificar(quadro: np.ndarray) -> bytes:
        ok, buffer = cv2.imencode(".jpg", quadro, [int(cv2.IMWRITE_JPEG_QUALITY), QUALIDADE_JPEG])
        return buffer.tobytes() if ok else b""

    def _publicar(self, quadro: np.ndarray, **status) -> None:
        jpeg = self._codificar(quadro)
        with self._lock:
            self._jpeg = jpeg
            self._status.update(status)

    def _loop_seguro(self) -> None:
        """Envolve o loop: um erro de câmera/modelo vira status visível na PWA em vez de matar a thread em silêncio."""
        try:
            self._loop()
        except Exception as erro:  # noqa: BLE001 - queremos registrar qualquer falha
            import traceback
            traceback.print_exc()
            self._publicar(quadro_mensagem("Erro no servico de visao"), erro=str(erro))

    def _loop(self) -> None:
        captura = self._criar_captura(self.fonte)
        estimador = self._criar_estimador(self.cfg_pose)
        detector = DetectorQueda(LARGURA, ALTURA, self.cfg_queda, self.cfg_pose)
        t_anterior, fps = time.time(), 0.0

        try:
            while self._rodando and captura.rodando:
                quadro = captura.ler()
                if quadro is None:
                    time.sleep(0.005)
                    continue
                agora = time.time()
                self._ultimo_quadro_em = agora

                # Câmera desligada pelo gestor: não processa (economiza CPU) e mostra aviso.
                if not self.ativa:
                    self._publicar(quadro_mensagem("Camera pausada"), pessoas=0, estado="normal", fps=0.0)
                    time.sleep(0.2)
                    continue

                poses = estimador.processar(quadro, agora)
                pessoas, alertas = detector.processar(poses, agora)

                dt, t_anterior = agora - t_anterior, agora
                if dt > 0:
                    fps = 0.9 * fps + 0.1 * (1.0 / dt)  # média móvel para o número não "pular"

                tela = self._desenhar(quadro.copy(), pessoas, fps)

                for evento in alertas:
                    caminho = self.notificador.notificar(evento, tela)
                    confianca = min(evento.angulo_tronco / 90.0, 1.0)  # proxy simples: quão horizontal está o tronco
                    self.banco.registrar_alerta(self.camera["id"], evento.id_pessoa, evento.tipo, confianca, caminho)

                estados = {p.estado for p in pessoas}
                estado_geral = ("alerta" if Estado.ALERTA in estados
                                else "atencao" if estados & {Estado.CAINDO, Estado.NO_CHAO} else "normal")
                self._publicar(tela, fps=round(fps, 1), estado=estado_geral, erro=None,
                               pessoas=sum(1 for p in pessoas if p.pose is not None))
        finally:
            captura.fechar()
            estimador.fechar()
