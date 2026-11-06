"""
app.py - Rotas da API usadas pela PWA.

Recursos (mesmos nomes do Quadro 8 da documentação, com prefixo /api):
    GET    /api/status              estado geral, FPS, pessoas, pendentes
    GET    /api/quadro              quadro atual em JPEG (a PWA busca em sequência: vídeo sem prender conexão)
    GET    /api/video               vídeo MJPEG contínuo (para VLC/outros; a PWA não usa)
    GET    /api/alertas             lista com filtros ?status=&tipo=&limite=
    PATCH  /api/alertas/{id}        resolver ou marcar falso alarme
    GET    /api/alertas/{id}/imagem foto do momento do alerta
    GET    /api/cameras             câmeras cadastradas
    PUT    /api/cameras/{id}        ligar/desligar, renomear
    GET    /api/configuracao        sensibilidade
    PUT    /api/configuracao
    GET    /api/contatos            contatos de emergência
    POST   /api/contatos
    DELETE /api/contatos/{id}
    GET    /api/push/chave          chave pública VAPID (a PWA usa para assinar)
    POST   /api/push/assinaturas    registra o aparelho para receber push
    DELETE /api/push/assinaturas    cancela
    GET    /api/push/aparelhos      aparelhos cadastrados (PATCH/DELETE /{id} renomeia/remove)
    GET    /api/push/envios         últimos envios de push (OK/FALHA)
    WS     /api/ws                  tempo real: status a cada 1 s + alertas novos na hora

Ainda sem login/JWT (previsto na API Node.js). Por isso o servidor escuta só em
127.0.0.1 por padrão; ver servidor.py --host.
"""

import asyncio
import os
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .banco import Banco
from .sensibilidade import aplicar_sensibilidade, rotulo_sensibilidade
from .servico_visao import ServicoVisao

FPS_VIDEO = 15            # o navegador não precisa de 30 FPS; metade economiza CPU e rede
INTERVALO_STATUS_S = 1.0  # frequência das atualizações pelo WebSocket


# ---------------------------------------------------------------- modelos de entrada (validação automática)
class TratarAlerta(BaseModel):
    status: Literal["RESOLVIDO", "FALSO_ALARME"]
    tratado_por: str = Field(default="Cuidador", max_length=120)


class AtualizarCamera(BaseModel):
    nome: Optional[str] = Field(default=None, max_length=80)
    local: Optional[str] = Field(default=None, max_length=60)
    ativa: Optional[bool] = None


class Configuracao(BaseModel):
    sensibilidade: float = Field(ge=0.0, le=1.0)


class ChavesPush(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class AssinaturaPush(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000, pattern=r"^https://")
    keys: ChavesPush
    nome: Optional[str] = Field(default=None, max_length=80)


class RenomearAparelho(BaseModel):
    nome: str = Field(min_length=1, max_length=80)


class RemoverAssinatura(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)


class NovoContato(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    telefone: str = Field(min_length=3, max_length=20, pattern=r"^[0-9+()\-\s]+$")
    tipo: str = Field(default="Familiar", max_length=30)


def criar_app(banco: Banco, servico: ServicoVisao, pasta_web: Optional[str] = None, push=None) -> FastAPI:
    """Fábrica da aplicação: recebe as dependências prontas (facilita os testes)."""
    app = FastAPI(title="Sentinela API", version="0.1.0")

    # Aplica a sensibilidade salva ao detector já na inicialização.
    aplicar_sensibilidade(servico.cfg_queda, banco.obter_sensibilidade())

    def montar_status() -> dict:
        cameras = banco.listar_cameras()
        sensibilidade = banco.obter_sensibilidade()
        return {
            **servico.status(),
            "pendentes": banco.contar_pendentes(),
            "cameras_ativas": sum(1 for c in cameras if c["ativa"]),
            "cameras_total": len(cameras),
            "sensibilidade": sensibilidade,
            "sensibilidade_rotulo": rotulo_sensibilidade(sensibilidade),
        }

    # ------------------------------------------------------------ status e vídeo
    @app.get("/api/status")
    def obter_status():
        return montar_status()

    @app.get("/api/quadro")
    def quadro_atual():
        # Requisição curta (abre, entrega 1 JPEG, fecha). O navegador limita ~6 conexões por
        # servidor; um stream contínuo por <img> esgotava esse limite e congelava a interface.
        return Response(content=servico.jpeg_atual(), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/video")
    async def video(request: Request):
        async def gerar():
            # Formato multipart/x-mixed-replace: cada parte é um JPEG que substitui o anterior.
            while not await request.is_disconnected():
                quadro = servico.jpeg_atual()
                yield b"--quadro\r\nContent-Type: image/jpeg\r\n\r\n" + quadro + b"\r\n"
                await asyncio.sleep(1 / FPS_VIDEO)
        return StreamingResponse(gerar(), media_type="multipart/x-mixed-replace; boundary=quadro",
                                 headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------ alertas
    @app.get("/api/alertas")
    def listar_alertas(status: Optional[str] = None, tipo: Optional[str] = None, limite: int = 100):
        return banco.listar_alertas(status=status, tipo=tipo, limite=min(max(limite, 1), 500))

    @app.patch("/api/alertas/{alerta_id}")
    def tratar_alerta(alerta_id: int, dados: TratarAlerta):
        if banco.obter_alerta(alerta_id) is None:
            raise HTTPException(404, "Alerta não encontrado")
        return banco.tratar_alerta(alerta_id, dados.status, dados.tratado_por)

    @app.get("/api/alertas/{alerta_id}/imagem")
    def imagem_alerta(alerta_id: int):
        alerta = banco.obter_alerta(alerta_id)
        # O caminho vem do banco (gravado pelo próprio serviço), nunca da URL: sem risco de path traversal.
        if not alerta or not alerta["imagem"] or not os.path.exists(alerta["imagem"]):
            raise HTTPException(404, "Imagem não disponível")
        return FileResponse(alerta["imagem"], media_type="image/jpeg")

    # ------------------------------------------------------------ câmeras
    @app.get("/api/cameras")
    def listar_cameras():
        return banco.listar_cameras()

    @app.put("/api/cameras/{camera_id}")
    def atualizar_camera(camera_id: int, dados: AtualizarCamera):
        camera = banco.atualizar_camera(camera_id, **dados.model_dump())
        if camera is None:
            raise HTTPException(404, "Câmera não encontrada")
        if camera_id == servico.camera["id"]:
            servico.ativa = camera["ativa"]  # efeito imediato no serviço de visão
        return camera

    # ------------------------------------------------------------ configuração
    @app.get("/api/configuracao")
    def obter_configuracao():
        s = banco.obter_sensibilidade()
        return {"sensibilidade": s, "rotulo": rotulo_sensibilidade(s)}

    @app.put("/api/configuracao")
    def salvar_configuracao(dados: Configuracao):
        banco.salvar_sensibilidade(dados.sensibilidade)
        aplicar_sensibilidade(servico.cfg_queda, dados.sensibilidade)
        return {"sensibilidade": dados.sensibilidade, "rotulo": rotulo_sensibilidade(dados.sensibilidade)}

    # ------------------------------------------------------------ contatos de emergência
    @app.get("/api/contatos")
    def listar_contatos():
        return banco.listar_contatos()

    @app.post("/api/contatos", status_code=201)
    def criar_contato(dados: NovoContato):
        return banco.criar_contato(dados.nome.strip(), dados.telefone.strip(), dados.tipo.strip())

    @app.delete("/api/contatos/{contato_id}", status_code=204)
    def remover_contato(contato_id: int):
        banco.remover_contato(contato_id)

    # ------------------------------------------------------------ tempo real
    # ---- Web Push (aviso com o app fechado)
    @app.get("/api/push/chave")
    def chave_push():
        if push is None or not push.configurado:
            raise HTTPException(503, "Push não configurado no servidor")
        return {"chave": push.chave_publica}

    @app.post("/api/push/assinaturas", status_code=204)
    def assinar_push(dados: AssinaturaPush):
        banco.salvar_assinatura(dados.endpoint, dados.keys.p256dh, dados.keys.auth,
                                dados.nome.strip() if dados.nome and dados.nome.strip() else None)

    @app.get("/api/push/aparelhos")
    def listar_aparelhos():
        return banco.listar_aparelhos()

    @app.patch("/api/push/aparelhos/{aparelho_id}")
    def renomear_aparelho(aparelho_id: int, dados: RenomearAparelho):
        if not banco.renomear_aparelho(aparelho_id, dados.nome.strip()):
            raise HTTPException(404, "Aparelho não encontrado")
        return {"id": aparelho_id, "nome": dados.nome.strip()}

    @app.delete("/api/push/aparelhos/{aparelho_id}", status_code=204)
    def remover_aparelho(aparelho_id: int):
        if not banco.remover_aparelho(aparelho_id):
            raise HTTPException(404, "Aparelho não encontrado")

    @app.get("/api/push/envios")
    def listar_envios(limite: int = 50):
        return banco.listar_envios_push(min(max(limite, 1), 200))

    @app.delete("/api/push/assinaturas", status_code=204)
    def cancelar_push(dados: RemoverAssinatura):
        banco.remover_assinatura(dados.endpoint)

    @app.websocket("/api/ws")
    async def tempo_real(ws: WebSocket):
        await ws.accept()
        # Consultas ao banco rodam em outra thread (asyncio.to_thread): com o PostgreSQL num
        # servidor, cada consulta leva alguns ms de rede e não pode bloquear o loop da API.
        ultimo_id = await asyncio.to_thread(banco.ultimo_alerta_id)  # só avisa alertas novos
        try:
            while True:
                novos = await asyncio.to_thread(banco.listar_alertas, depois_de_id=ultimo_id)
                for alerta in reversed(novos):
                    await ws.send_json({"tipo": "alerta", "alerta": alerta})
                    ultimo_id = max(ultimo_id, alerta["id"])
                await ws.send_json({"tipo": "status", "status": await asyncio.to_thread(montar_status)})
                await asyncio.sleep(INTERVALO_STATUS_S)
        except (WebSocketDisconnect, RuntimeError):
            pass  # navegador fechou a aba

    # ------------------------------------------------------------ arquivos da PWA (build do React)
    # Montado por último para não "engolir" as rotas /api.
    if pasta_web and os.path.exists(os.path.join(pasta_web, "index.html")):
        app.mount("/", StaticFiles(directory=pasta_web, html=True), name="pwa")

    return app
