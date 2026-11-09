"""
cliente_agente.py - Lado do AGENTE: fala com o painel (rotas_agente.py) por HTTPS.

Peças
-----
ClienteAgente   uma chamada HTTP por operação (registrar câmera, config, status, quadro, alerta).
BancoRemoto     faz de conta que é o Banco para o ServicoVisao: `registrar_alerta` não grava em banco nenhum,
                guarda o alerta numa FILA EM DISCO e um trabalhador o envia ao painel. Se a internet cair, o
                alerta fica na pasta e segue quando a rede voltar (também depois de reiniciar o agente).
Sincronizador   a cada segundo manda um quadro, a cada poucos segundos o status, e a cada 10 s busca a
                configuração do painel (sensibilidade, câmera ligada, área da cama).

Privacidade: a foto do alerta só sai do local para o painel; depois do envio a cópia local é apagada
(AGENTE_GUARDAR_FOTOS=1 mantém).
"""

import base64
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

import requests

TIMEOUT_S = 10
ESPERA_MAX_S = 60


class ErroDefinitivo(Exception):
    """O painel recusou (4xx): repetir não adianta."""


class ClienteAgente:
    def __init__(self, url: str, token: str, sessao=None, timeout: float = TIMEOUT_S):
        self.url = url.rstrip("/")
        self._cabecalho = {"Authorization": f"Bearer {token}"}
        self.sessao = sessao or requests.Session()
        self.timeout = timeout

    def _chamar(self, metodo: str, caminho: str, **kw):
        resposta = getattr(self.sessao, metodo)(self.url + caminho, headers={**self._cabecalho, **kw.pop("headers", {})},
                                                timeout=self.timeout, **kw)
        if 400 <= resposta.status_code < 500 and resposta.status_code != 429:
            raise ErroDefinitivo(f"{resposta.status_code}: {resposta.text[:200]}")
        resposta.raise_for_status()
        return resposta

    def registrar_camera(self, nome: str, local: str) -> Dict[str, Any]:
        return self._chamar("post", "/api/agente/camera", json={"nome": nome, "local": local}).json()

    def configuracao(self, camera_id: int) -> Dict[str, Any]:
        return self._chamar("get", "/api/agente/config", params={"camera_id": camera_id}).json()

    def enviar_status(self, camera_id: int, status: Dict[str, Any]) -> None:
        corpo = {"camera_id": camera_id, "fps": float(status.get("fps", 0.0)), "pessoas": int(status.get("pessoas", 0)),
                 "estado": status.get("estado", "normal"), "camera_online": bool(status.get("camera_online", True)),
                 "erro": (str(status["erro"])[:200] if status.get("erro") else None)}
        self._chamar("post", "/api/agente/status", json=corpo)

    def enviar_quadro(self, camera_id: int, jpeg: bytes) -> bool:
        """Envia um quadro. Devolve True se alguém está assistindo (então vale mandar mais quadros por segundo)."""
        resposta = self._chamar("post", "/api/agente/quadro", params={"camera_id": camera_id}, data=jpeg,
                                headers={"Content-Type": "image/jpeg"})
        try:
            return bool(resposta.json().get("assistindo", True))
        except ValueError:  # painel antigo (204 sem corpo): na dúvida, trata como "há espectador"
            return True

    def enviar_alerta(self, camera_id: int, track_id: int, tipo: str, confianca: float,
                      jpeg: Optional[bytes], detalhes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        corpo: Dict[str, Any] = {"camera_id": camera_id, "track_id": track_id, "tipo": tipo,
                                 "confianca": min(max(float(confianca), 0.0), 1.0)}
        if detalhes:
            corpo["detalhes"] = detalhes
        if jpeg:
            corpo["imagem_jpeg_b64"] = base64.b64encode(jpeg).decode("ascii")
        return self._chamar("post", "/api/agente/alertas", json=corpo).json()


class BancoRemoto:
    """Substitui o Banco no ServicoVisao: o alerta vira um arquivo na fila e é enviado ao painel."""

    def __init__(self, cliente: ClienteAgente, pasta_fila: str = "fila_agente", guardar_fotos: bool = False,
                 espera_inicial_s: float = 2.0):
        self.cliente = cliente
        self.pasta_fila = pasta_fila
        self.guardar_fotos = guardar_fotos
        self._espera_inicial_s = espera_inicial_s
        self._parar = threading.Event()
        self._acordar = threading.Event()
        self._thread: Optional[threading.Thread] = None
        os.makedirs(pasta_fila, exist_ok=True)

    # ---- usado pelo ServicoVisao
    def registrar_alerta(self, camera_id: int, track_id: int, tipo_logica: str, confianca: float,
                         imagem: Optional[str], detalhes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        item = {"camera_id": camera_id, "track_id": track_id, "tipo": tipo_logica, "confianca": confianca,
                "imagem": imagem, "detalhes": detalhes, "criado_em": time.time()}
        nome = f"{int(time.time() * 1000):013d}_{uuid.uuid4().hex[:8]}.json"
        temporario = os.path.join(self.pasta_fila, nome + ".tmp")
        with open(temporario, "w", encoding="utf-8") as arquivo:
            json.dump(item, arquivo)
        os.replace(temporario, os.path.join(self.pasta_fila, nome))  # grava inteiro ou não grava
        self._acordar.set()
        return {"id": None, "tipo": tipo_logica, "camera_id": camera_id, "pendente_de_envio": True}

    # ---- trabalhador
    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._trabalhar, name="fila-agente", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        self._acordar.set()
        if self._thread:
            self._thread.join(timeout=3)

    def pendentes(self):
        return sorted(f for f in os.listdir(self.pasta_fila) if f.endswith(".json"))

    def enviar_pendentes(self) -> bool:
        """Tenta enviar tudo, na ordem. Devolve True se a fila ficou vazia."""
        for nome in self.pendentes():
            caminho = os.path.join(self.pasta_fila, nome)
            try:
                with open(caminho, encoding="utf-8") as arquivo:
                    item = json.load(arquivo)
            except (OSError, ValueError):
                os.replace(caminho, caminho + ".invalido")
                continue
            jpeg = None
            if item.get("imagem") and os.path.exists(item["imagem"]):
                with open(item["imagem"], "rb") as foto:
                    jpeg = foto.read()
            try:
                self.cliente.enviar_alerta(item["camera_id"], item["track_id"], item["tipo"], item["confianca"], jpeg, item.get("detalhes"))
            except ErroDefinitivo as erro:
                print(f"[Agente] alerta descartado, o painel recusou: {erro}")
            except requests.RequestException as erro:
                print(f"[Agente] sem conexão com o painel ({erro.__class__.__name__}); o alerta fica na fila")
                return False
            if item.get("imagem") and not self.guardar_fotos:
                try:
                    os.remove(item["imagem"])  # a foto já está no painel: não deixar cópia no computador do local
                except OSError:
                    pass
            os.remove(caminho)
        return True

    def _trabalhar(self) -> None:
        espera = self._espera_inicial_s
        while not self._parar.is_set():
            if self.enviar_pendentes():
                espera = self._espera_inicial_s
                self._acordar.wait(timeout=30)  # dorme até chegar um alerta novo (ou 30 s)
                self._acordar.clear()
            else:
                self._parar.wait(espera)
                espera = min(espera * 2, ESPERA_MAX_S)


class Sincronizador:
    """Vídeo ao vivo, status e configuração, cada um no seu ritmo.

    Vídeo: uma thread própria manda o quadro mais recente. Com espectador no painel, o ritmo é `fps_video`
    (padrão 6 quadros/s); sem ninguém olhando, 1 quadro a cada `espera_sem_espectador_s` (padrão 2 s), o que poupa a
    internet do local da câmera. Status a cada 3 s e configuração a cada 10 s ficam em outra thread, para uma chamada
    lenta de status não atrasar o vídeo.
    """

    def __init__(self, cliente: ClienteAgente, servico, camera_id: int, aplicar_sensibilidade=None,
                 fps_video: float = 6.0, espera_sem_espectador_s: float = 2.0,
                 intervalo_status_s: float = 3.0, intervalo_config_s: float = 10.0):
        self.cliente = cliente
        self.servico = servico
        self.camera_id = camera_id
        self._aplicar_sensibilidade = aplicar_sensibilidade
        self._pausa_com_espectador_s = 1.0 / max(fps_video, 0.2)
        self._pausa_sem_espectador_s = espera_sem_espectador_s
        self._intervalos = (intervalo_status_s, intervalo_config_s)
        self._parar = threading.Event()
        self._threads: list = []
        self.assistindo = False

    def iniciar(self) -> None:
        self._threads = [threading.Thread(target=self._loop_video, name="video-agente", daemon=True),
                         threading.Thread(target=self._loop_status, name="status-agente", daemon=True)]
        for t in self._threads:
            t.start()

    def parar(self) -> None:
        self._parar.set()
        for t in self._threads:
            t.join(timeout=3)

    def enviar_quadro_uma_vez(self) -> None:
        try:
            self.assistindo = self.cliente.enviar_quadro(self.camera_id, self.servico.jpeg_atual())
        except (requests.RequestException, ErroDefinitivo) as erro:
            self.assistindo = False
            print(f"[Agente] quadro não enviado ({erro.__class__.__name__}): {str(erro)[:100]}")

    def sincronizar_uma_vez(self, quadro=True, status=True, config=True) -> None:
        """Cada parte falha sozinha: um erro de rede em uma não impede as outras."""
        if quadro:
            self.enviar_quadro_uma_vez()
        passos = []
        if status:
            passos.append(lambda: self.cliente.enviar_status(self.camera_id, self.servico.status()))
        if config:
            passos.append(self._buscar_configuracao)
        for passo in passos:
            try:
                passo()
            except (requests.RequestException, ErroDefinitivo) as erro:
                print(f"[Agente] sincronização falhou ({erro.__class__.__name__}): {str(erro)[:120]}")

    def _buscar_configuracao(self) -> None:
        config = self.cliente.configuracao(self.camera_id)
        if self._aplicar_sensibilidade is not None:
            self._aplicar_sensibilidade(self.servico.cfg_queda, config["sensibilidade"])
        self.servico.ativa = bool(config["ativa"])
        self.servico.area_cama = list(config["area_cama"])  # o ServicoVisao repassa ao detector no próximo quadro

    def _loop_video(self) -> None:
        while not self._parar.is_set():
            inicio = time.monotonic()
            self.enviar_quadro_uma_vez()
            ritmo = self._pausa_com_espectador_s if self.assistindo else self._pausa_sem_espectador_s
            self._parar.wait(max(0.0, ritmo - (time.monotonic() - inicio)))

    def _loop_status(self) -> None:
        t_status, t_config = self._intervalos
        ultimo = {"status": 0.0, "config": 0.0}
        while not self._parar.is_set():
            agora = time.monotonic()
            devido_status, devido_config = agora - ultimo["status"] >= t_status, agora - ultimo["config"] >= t_config
            if devido_status or devido_config:
                self.sincronizar_uma_vez(quadro=False, status=devido_status, config=devido_config)
                ultimo["status"] = agora if devido_status else ultimo["status"]
                ultimo["config"] = agora if devido_config else ultimo["config"]
            self._parar.wait(0.25)
