"""
rotas_agente.py - API que o AGENTE DE VISÃO usa para falar com o painel (VPS).

Agente = programa que roda onde a câmera é alcançável (ex.: um computador pequeno no local), detecta
quedas e envia o resultado ao painel por HTTPS. O vídeo NUNCA sai de lá: só viajam o alerta, uma foto do
momento e um quadro por segundo para a tela "ao vivo".

Autenticação: cabeçalho  Authorization: Bearer <chave do agente>  (gerada com `python -m sentinela_api.agentes criar`).
Não usa o login por cookie dos usuários: são portas diferentes, com chaves diferentes.

    POST /api/agente/camera    registra (ou reencontra) a câmera deste agente
    GET  /api/agente/config    sensibilidade, câmera ligada/desligada e área da cama (o agente consulta de tempos em tempos)
    POST /api/agente/status    fps, pessoas, estado (batimento: mostra "câmera online" no painel)
    POST /api/agente/quadro    um JPEG para o vídeo ao vivo; a resposta diz se há espectador ({"assistindo": true})
    POST /api/agente/alertas   alerta + foto; o painel grava, avisa o push e o WhatsApp
"""

import asyncio
import base64
import binascii
import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .agentes import hash_token
from .banco import Banco

MAX_FOTO_BYTES = 2 * 1024 * 1024
MAX_QUADRO_BYTES = 600 * 1024
MAX_DETALHES_BYTES = 16 * 1024  # detalhes maiores que isso são ignorados (o alerta sai igual)
INTERVALO_CONTATO_S = 30  # o "último contato" do agente é gravado no máximo a cada 30 s (o quadro chega a cada 1 s)
# A chave e o dono de cada câmera são lembrados por alguns segundos: o vídeo (até 8 quadros/s por câmera) não consulta
# o banco a cada quadro. Revogar uma chave vale em no máximo CACHE_AGENTE_S segundos (alertas também revalidam).
CACHE_AGENTE_S = 10.0


class RegistrarCamera(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    local: str = Field(default="", max_length=60)


class StatusAgente(BaseModel):
    camera_id: int
    fps: float = Field(default=0.0, ge=0, le=1000)
    pessoas: int = Field(default=0, ge=0, le=100)
    estado: Literal["normal", "atencao", "alerta"] = "normal"
    camera_online: bool = True
    deteccao: bool = True  # False = só transmite vídeo (ex.: câmera do navegador na etapa 1): o painel avisa "SÓ VÍDEO"
    erro: Optional[str] = Field(default=None, max_length=200)


class NovoAlertaAgente(BaseModel):
    camera_id: int
    track_id: int = Field(ge=0, le=10_000_000)
    tipo: Literal["queda", "pessoa_no_chao"]
    confianca: float = Field(ge=0.0, le=1.0)
    imagem_jpeg_b64: Optional[str] = Field(default=None, max_length=MAX_FOTO_BYTES * 4 // 3 + 64)
    detalhes: Optional[Dict[str, Any]] = None  # números do momento do alerta (ângulo, velocidade, trajetória...)


def _e_jpeg(dados: bytes) -> bool:
    return dados[:3] == b"\xff\xd8\xff"


def criar_rotas_agente(banco: Banco, servico, push=None, notificador_remoto=None,
                       pasta_fotos: str = "alertas_queda") -> APIRouter:
    router = APIRouter(prefix="/api/agente", tags=["agente"])
    os.makedirs(pasta_fotos, exist_ok=True)
    ultimo_contato: Dict[int, float] = {}
    lock = threading.Lock()
    agentes_em_cache: Dict[str, tuple] = {}   # hash da chave -> (agente ou None, validade)
    donos_em_cache: Dict[int, tuple] = {}     # camera_id -> (url_stream, câmera, validade)

    def _agente_da_chave(token_hash: str, usar_cache: bool = True) -> Optional[Dict[str, Any]]:
        agora = time.monotonic()
        with lock:
            item = agentes_em_cache.get(token_hash)
        if usar_cache and item and item[1] > agora:
            return item[0]
        agente = banco.obter_agente_por_token(token_hash)
        with lock:
            if len(agentes_em_cache) > 1000:
                agentes_em_cache.clear()
            agentes_em_cache[token_hash] = (agente, agora + CACHE_AGENTE_S)
        return agente

    def _autenticar(authorization: Optional[str], usar_cache: bool) -> Dict[str, Any]:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Chave do agente ausente")
        agente = _agente_da_chave(hash_token(authorization[7:].strip()), usar_cache)
        if agente is None:
            raise HTTPException(401, "Chave do agente inválida ou revogada")
        agora = time.monotonic()
        with lock:
            gravar = agora - ultimo_contato.get(agente["id"], -1e9) >= INTERVALO_CONTATO_S
            if gravar:
                ultimo_contato[agente["id"]] = agora
        if gravar:
            banco.registrar_contato_agente(agente["id"])
        return agente

    def autenticar(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
        return _autenticar(authorization, usar_cache=True)

    def autenticar_sem_cache(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
        """Para registrar câmera e ALERTA: sempre confere no banco (revogação vale na hora)."""
        return _autenticar(authorization, usar_cache=False)

    def camera_do_agente(agente: Dict[str, Any], camera_id: int, usar_cache: bool = False) -> Dict[str, Any]:
        """Um agente só mexe nas câmeras que ele mesmo registrou."""
        agora = time.monotonic()
        with lock:
            item = donos_em_cache.get(camera_id)
        if usar_cache and item and item[2] > agora:
            origem, camera = item[0], item[1]
        else:
            camera = banco.obter_camera(camera_id)
            origem = banco.url_stream_da_camera(camera_id) or ""
            with lock:
                donos_em_cache[camera_id] = (origem, camera, agora + CACHE_AGENTE_S)
        if camera is None or not origem.startswith(f"agente:{agente['id']}:"):
            raise HTTPException(404, "Câmera não encontrada para este agente")
        return camera

    @router.post("/camera")
    def registrar_camera(dados: RegistrarCamera, agente=Depends(autenticar_sem_cache)):
        camera = banco.garantir_camera(dados.nome.strip(), dados.local.strip(), f"agente:{agente['id']}:{dados.nome.strip()}")
        return {**banco.obter_camera(camera["id"]), "sensibilidade": banco.obter_sensibilidade()}

    @router.get("/config")
    def configuracao(camera_id: int, agente=Depends(autenticar)):
        camera = camera_do_agente(agente, camera_id)
        return {"sensibilidade": banco.obter_sensibilidade(), "ativa": camera["ativa"], "area_cama": camera["area_cama"]}

    @router.post("/status", status_code=204)
    def receber_status(dados: StatusAgente, agente=Depends(autenticar)):
        camera_do_agente(agente, dados.camera_id)
        servico.receber_status(dados.camera_id, dados.model_dump(exclude={"camera_id"}))

    @router.post("/quadro")
    async def receber_quadro(camera_id: int, request: Request, agente=Depends(autenticar)):
        """Recebe um quadro e responde se alguém está assistindo: o agente manda ~6 quadros/s só com espectador.

        Esta rota é async (precisa ler o corpo). Tudo que toca o banco roda em outra thread (asyncio.to_thread):
        antes, as consultas rodavam direto no loop da API e cada quadro travava o painel inteiro durante a ida ao banco.
        """
        if int(request.headers.get("content-length") or 0) > MAX_QUADRO_BYTES:
            raise HTTPException(413, "Quadro grande demais")  # recusa antes de ler o corpo para a memória
        await asyncio.to_thread(camera_do_agente, agente, camera_id, True)
        corpo = await request.body()
        if len(corpo) > MAX_QUADRO_BYTES:
            raise HTTPException(413, "Quadro grande demais")
        if not _e_jpeg(corpo):
            raise HTTPException(422, "O quadro precisa ser um JPEG")
        servico.receber_quadro(camera_id, corpo)
        return {"assistindo": servico.alguem_assistindo(camera_id)}

    @router.post("/alertas", status_code=201)
    def receber_alerta(dados: NovoAlertaAgente, agente=Depends(autenticar_sem_cache)):
        camera_do_agente(agente, dados.camera_id)
        caminho = None
        if dados.imagem_jpeg_b64:
            try:
                foto = base64.b64decode(dados.imagem_jpeg_b64, validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(422, "Foto em base64 inválido")
            if len(foto) > MAX_FOTO_BYTES:
                raise HTTPException(413, "Foto grande demais")
            if not _e_jpeg(foto):
                raise HTTPException(422, "A foto precisa ser um JPEG")
            # O nome do arquivo é gerado AQUI: nada vindo do agente entra no caminho (sem path traversal).
            nome = f"{datetime.now():%Y%m%d_%H%M%S}_{dados.tipo}_c{dados.camera_id}_{uuid.uuid4().hex[:8]}.jpg"
            caminho = os.path.join(pasta_fotos, nome)
            with open(caminho, "wb") as arquivo:
                arquivo.write(foto)
        detalhes = dados.detalhes if dados.detalhes and len(json.dumps(dados.detalhes)) <= MAX_DETALHES_BYTES else None
        alerta = banco.registrar_alerta(dados.camera_id, dados.track_id, dados.tipo, dados.confianca, caminho, detalhes=detalhes)
        if push is not None:
            push.avisar(alerta)
        if notificador_remoto is not None:
            notificador_remoto.avisar(alerta)
        return alerta

    def esquecer_chaves() -> None:
        """Chamado quando uma chave é revogada/trocada pela tela: a mudança vale na hora, sem esperar o cache."""
        with lock:
            agentes_em_cache.clear()
            donos_em_cache.clear()

    router.esquecer_chaves = esquecer_chaves
    return router
