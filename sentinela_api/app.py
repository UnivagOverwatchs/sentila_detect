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
    DELETE /api/cameras/{id}        excluir a câmera e o histórico dela (alertas e fotos)
    PUT    /api/cameras/{id}/area-cama  marcar onde fica a cama (deitar ali não gera alerta)
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

Login (autenticacao.py): só é exigido com LOGIN_OBRIGATORIO=1 (servidor público). Sem isso o painel
fica aberto e o servidor escuta só em 127.0.0.1 por padrão; ver servidor.py --host.
    POST /api/login  /api/logout   GET /api/eu   GET/POST/PATCH /api/usuarios (só ADMIN)

Agente de visão (rotas_agente.py): /api/agente/* usa chave própria (Bearer), não o login por cookie.
"""

import asyncio
import math
import os
from datetime import datetime
from typing import Annotated, Literal, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.requests import HTTPConnection
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agentes as chaves_de_agente
from . import autenticacao as auth
from .banco import Banco
from .rotas_agente import criar_rotas_agente
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


Ponto = Annotated[list[float], Field(min_length=2, max_length=2)]


class AreaCama(BaseModel):
    """Zonas de cama: até 4 polígonos de 3 a 12 pontos, com x e y entre 0 e 1 (fração da imagem)."""
    poligonos: list[Annotated[list[Ponto], Field(min_length=3, max_length=12)]] = Field(default_factory=list, max_length=4)


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


class Login(BaseModel):
    usuario: str = Field(min_length=1, max_length=60)
    senha: str = Field(min_length=1, max_length=200)


class NovoUsuario(BaseModel):
    usuario: str = Field(pattern=r"^[a-z0-9._-]{3,60}$")
    nome: str = Field(min_length=1, max_length=120)
    senha: str = Field(min_length=1, max_length=200)
    papel: Literal["ADMIN", "CUIDADOR"] = "CUIDADOR"


class AtualizarUsuario(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1, max_length=120)
    papel: Optional[Literal["ADMIN", "CUIDADOR"]] = None
    ativo: Optional[bool] = None
    senha: Optional[str] = Field(default=None, min_length=1, max_length=200)


class NovoAgente(BaseModel):
    nome: str = Field(pattern=r"^[\w .\-]{1,80}$")  # letras, números, espaço, ponto e hífen


class AtualizarAgente(BaseModel):
    ativo: bool


class NovoContato(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    telefone: str = Field(min_length=3, max_length=20, pattern=r"^[0-9+()\-\s]+$")
    tipo: str = Field(default="Familiar", max_length=30)


# Rotas abertas mesmo com login obrigatório (a tela de login precisa delas).
ROTAS_PUBLICAS = {"/api/login", "/api/logout", "/api/eu"}
# CUIDADOR só lê estas áreas; quem altera é o ADMIN.
ADMIN_SO_ESCRITA = ("/api/configuracao", "/api/cameras", "/api/contatos")
# Áreas inteiras só do ADMIN.
ADMIN_TOTAL = ("/api/usuarios", "/api/agentes", "/api/push/aparelhos", "/api/push/envios")


AREA_MINIMA_CAMA = 0.02  # fração da imagem: abaixo disso a "cama" é praticamente uma linha


def _area_poligono(poligono) -> float:
    """Área pela fórmula do cadarço (coordenadas de 0 a 1 = fração da imagem)."""
    soma = 0.0
    for i, (x1, y1) in enumerate(poligono):
        x2, y2 = poligono[(i + 1) % len(poligono)]
        soma += x1 * y2 - x2 * y1
    return abs(soma) / 2


def _orientacao(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _poligono_se_cruza(poligono) -> bool:
    """True se dois lados que não são vizinhos se cruzam (contorno em 'gravata' ou zigue-zague)."""
    n = len(poligono)
    for i in range(n):
        a, b = poligono[i], poligono[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue  # lados vizinhos compartilham um ponto
            c, d = poligono[j], poligono[(j + 1) % n]
            if (_orientacao(a, b, c) * _orientacao(a, b, d) < 0) and (_orientacao(c, d, a) * _orientacao(c, d, b) < 0):
                return True
    return False


def _exige_admin(metodo: str, caminho: str) -> bool:
    if any(caminho == a or caminho.startswith(a + "/") for a in ADMIN_TOTAL):
        return True
    return metodo not in ("GET", "HEAD", "OPTIONS") and any(
        caminho == a or caminho.startswith(a + "/") for a in ADMIN_SO_ESCRITA)


def criar_app(banco: Banco, servico: ServicoVisao, pasta_web: Optional[str] = None, push=None,
              exigir_login: bool = False, cookie_seguro: bool = False,
              limitador: Optional[auth.LimitadorLogin] = None,
              pasta_fotos: str = "alertas_queda", notificador_remoto=None) -> FastAPI:
    """Fábrica da aplicação: recebe as dependências prontas (facilita os testes).

    exigir_login=False mantém o painel aberto (uso local). Em servidor público, use True.
    """
    limitador = limitador or auth.LimitadorLogin()

    def usuario_da_conexao(conn: HTTPConnection) -> Optional[dict]:
        token = conn.cookies.get(auth.COOKIE_SESSAO)
        return banco.obter_usuario_da_sessao(auth.hash_token(token)) if token else None

    def proteger(conn: HTTPConnection) -> None:
        """Roda antes de toda rota HTTP: confere origem (CSRF), login e papel."""
        if conn.scope["type"] != "http":
            return  # o WebSocket confere o cookie por conta própria
        metodo, caminho = conn.scope["method"], conn.url.path
        if metodo not in ("GET", "HEAD", "OPTIONS"):
            origem = conn.headers.get("origin")
            if origem and urlparse(origem).netloc != conn.headers.get("host", ""):
                raise HTTPException(403, "Origem não permitida")
        if not exigir_login or caminho in ROTAS_PUBLICAS or not caminho.startswith("/api/"):
            return
        if caminho.startswith("/api/agente/"):
            return  # os agentes de visão se autenticam com a chave própria (rotas_agente.py), não com cookie
        usuario = usuario_da_conexao(conn)
        if usuario is None:
            raise HTTPException(401, "Não autenticado")
        if usuario["papel"] != "ADMIN" and _exige_admin(metodo, caminho):
            raise HTTPException(403, "Apenas administradores")
        conn.state.usuario = usuario

    app = FastAPI(title="Sentinela API", version="0.1.0", dependencies=[Depends(proteger)])

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
            "cameras": servico.estado_cameras(),  # a interface monta a grade e o seletor com isto
        }

    # ------------------------------------------------------------ status e vídeo
    @app.get("/api/status")
    def obter_status():
        return montar_status()

    @app.get("/api/quadro")
    def quadro_atual(camera_id: Optional[int] = None):
        # Requisição curta (abre, entrega 1 JPEG, fecha). O navegador limita ~6 conexões por
        # servidor; um stream contínuo por <img> esgotava esse limite e congelava a interface.
        jpeg = servico.jpeg_da_camera(camera_id) if camera_id is not None else servico.jpeg_atual()
        return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

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
    def tratar_alerta(alerta_id: int, dados: TratarAlerta, request: Request):
        if banco.obter_alerta(alerta_id) is None:
            raise HTTPException(404, "Alerta não encontrado")
        # Com login, quem tratou é o usuário da sessão (não o texto enviado pelo navegador).
        usuario = getattr(request.state, "usuario", None)
        return banco.tratar_alerta(alerta_id, dados.status, usuario["nome"] if usuario else dados.tratado_por)

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

    @app.delete("/api/cameras/{camera_id}", status_code=204)
    def excluir_camera(camera_id: int):
        """Exclui a câmera e todo o histórico dela (alertas, eventos e fotos). Só administrador (rota /api/cameras)."""
        local = None if hasattr(servico, "esquecer_camera") else getattr(servico, "camera", None)  # modo painel: não há câmera local
        if local and local["id"] == camera_id:
            raise HTTPException(409, "Esta é a câmera ligada neste computador. Desative-a (interruptor) em vez de excluir.")
        fotos = banco.excluir_camera(camera_id)
        if fotos is None:
            raise HTTPException(404, "Câmera não encontrada")
        if hasattr(servico, "esquecer_camera"):
            servico.esquecer_camera(camera_id)
        pasta = os.path.realpath(pasta_fotos)
        for caminho in fotos:  # só apaga arquivo que está dentro da pasta de fotos
            real = os.path.realpath(caminho)
            if os.path.commonpath([pasta, real]) == pasta and os.path.isfile(real):
                try:
                    os.remove(real)
                except OSError:
                    pass

    @app.put("/api/cameras/{camera_id}/area-cama")
    def salvar_area_cama(camera_id: int, dados: AreaCama):
        for poligono in dados.poligonos:
            if any(not (0.0 <= v <= 1.0) for ponto in poligono for v in ponto):
                raise HTTPException(422, "As coordenadas da cama devem ficar entre 0 e 1")
            if _area_poligono(poligono) < AREA_MINIMA_CAMA:
                raise HTTPException(422, "A área da cama ficou pequena demais (menos de 2% da imagem), quase uma linha. "
                                         "Marque os cantos dando a volta na cama: dois em cima e dois embaixo.")
            if _poligono_se_cruza(poligono):
                raise HTTPException(422, "O contorno da cama se cruza. Marque os cantos em sequência, dando a volta, sem cruzar linhas.")
        camera = banco.salvar_area_cama(camera_id, dados.poligonos) if banco.obter_camera(camera_id) else None
        if camera is None:
            raise HTTPException(404, "Câmera não encontrada")
        if camera_id == servico.camera["id"]:
            servico.area_cama = camera["area_cama"]  # vale já no próximo quadro
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
    # ------------------------------------------------------------ login e usuários
    def definir_cookie(resposta: Response, token: str) -> None:
        resposta.set_cookie(auth.COOKIE_SESSAO, token, max_age=auth.DURACAO_SESSAO_S, httponly=True,
                            samesite="lax", secure=cookie_seguro, path="/")

    @app.post("/api/login")
    def entrar(dados: Login, resposta: Response):
        chave = dados.usuario.strip().lower()
        espera = limitador.segundos_restantes(chave)
        if espera:
            raise HTTPException(429, f"Muitas tentativas. Tente de novo em {math.ceil(espera / 60)} min.",
                                headers={"Retry-After": str(espera)})
        registro = banco.obter_usuario_para_login(chave)
        # Verifica sempre (com hash falso se o usuário não existe): o tempo de resposta não revela quem existe.
        senha_ok = auth.verificar_senha(dados.senha, registro["senha_hash"] if registro else auth.HASH_FALSO)
        if not (registro and registro["ativo"] and senha_ok):
            limitador.registrar_erro(chave)
            raise HTTPException(401, "Usuário ou senha inválidos")
        limitador.registrar_sucesso(chave)
        token = auth.novo_token()
        banco.criar_sessao(auth.hash_token(token), registro["id"], auth.DURACAO_SESSAO_S)
        banco.limpar_sessoes_expiradas()
        definir_cookie(resposta, token)
        return {"usuario": registro["usuario"], "nome": registro["nome"], "papel": registro["papel"]}

    @app.post("/api/logout", status_code=204)
    def sair(request: Request, resposta: Response):
        token = request.cookies.get(auth.COOKIE_SESSAO)
        if token:
            banco.encerrar_sessao(auth.hash_token(token))
        resposta.delete_cookie(auth.COOKIE_SESSAO, path="/")

    @app.get("/api/eu")
    def quem_sou_eu(request: Request):
        """A tela usa isto ao abrir: diz se o login é exigido e quem está logado (sem dar erro 401)."""
        usuario = usuario_da_conexao(request) if exigir_login else None
        publico = {k: usuario[k] for k in ("usuario", "nome", "papel")} if usuario else None
        return {"login_obrigatorio": exigir_login, "usuario": publico}

    @app.get("/api/usuarios")
    def listar_usuarios():
        return banco.listar_usuarios()

    @app.post("/api/usuarios", status_code=201)
    def criar_usuario(dados: NovoUsuario):
        erro = auth.validar_senha_nova(dados.senha)
        if erro:
            raise HTTPException(422, erro)
        if banco.obter_usuario_para_login(dados.usuario):
            raise HTTPException(409, "Já existe um usuário com esse login")
        return banco.criar_usuario(dados.usuario, dados.nome.strip(), auth.hash_senha(dados.senha), dados.papel)

    @app.patch("/api/usuarios/{usuario_id}")
    def atualizar_usuario(usuario_id: int, dados: AtualizarUsuario, request: Request):
        alvo = banco.obter_usuario(usuario_id)
        if alvo is None:
            raise HTTPException(404, "Usuário não encontrado")
        eu = getattr(request.state, "usuario", None)
        if eu and eu["id"] == usuario_id and (dados.ativo is False or dados.papel == "CUIDADOR"):
            raise HTTPException(400, "Você não pode desativar nem rebaixar a si mesmo")
        senha_hash = None
        if dados.senha is not None:
            erro = auth.validar_senha_nova(dados.senha)
            if erro:
                raise HTTPException(422, erro)
            senha_hash = auth.hash_senha(dados.senha)
        atualizado = banco.atualizar_usuario(usuario_id, nome=dados.nome.strip() if dados.nome else None,
                                             papel=dados.papel, ativo=dados.ativo, senha_hash=senha_hash)
        if senha_hash or dados.ativo is False or dados.papel:
            banco.encerrar_sessoes_do_usuario(usuario_id)  # nova senha/desativação/novo papel: entra de novo
        return atualizado

    # ------------------------------------------------------------ chaves dos agentes de câmera (só ADMIN)
    def _agente_por_id(agente_id: int) -> dict:
        for agente in banco.listar_agentes():
            if agente["id"] == agente_id:
                return agente
        raise HTTPException(404, "Agente não encontrado")

    def _com_tempo(agente: dict) -> dict:
        """Acrescenta há quantos segundos o agente falou, medido no relógio do próprio servidor (sem ambiguidade de fuso)."""
        visto = agente.get("ultimo_contato")
        segundos = None
        if visto:
            try:
                segundos = max(0, int((datetime.now() - datetime.fromisoformat(str(visto))).total_seconds()))
            except ValueError:
                segundos = None
        return {**agente, "ultimo_contato_ha_s": segundos}

    @app.get("/api/agentes")
    def listar_agentes():
        return [_com_tempo(a) for a in banco.listar_agentes()]  # nunca inclui a chave: o banco só guarda o hash

    @app.post("/api/agentes", status_code=201)
    def criar_agente(dados: NovoAgente):
        nome = dados.nome.strip()
        if any(a["nome"] == nome for a in banco.listar_agentes()):
            raise HTTPException(409, "Já existe um agente com esse nome")
        token = chaves_de_agente.novo_token()
        agente = banco.criar_agente(nome, chaves_de_agente.hash_token(token))
        return {**agente, "token": token}  # a ÚNICA vez em que a chave é mostrada

    @app.post("/api/agentes/{agente_id}/nova-chave")
    def nova_chave_do_agente(agente_id: int):
        agente = _agente_por_id(agente_id)
        token = chaves_de_agente.novo_token()
        banco.trocar_token_do_agente(agente["nome"], chaves_de_agente.hash_token(token))
        return {**_com_tempo(_agente_por_id(agente_id)), "token": token}  # a chave antiga deixa de valer neste instante

    @app.patch("/api/agentes/{agente_id}")
    def ativar_ou_revogar_agente(agente_id: int, dados: AtualizarAgente):
        agente = _agente_por_id(agente_id)
        banco.definir_agente_ativo(agente["nome"], dados.ativo)
        return _com_tempo(_agente_por_id(agente_id))

    # ------------------------------------------------------------ agentes de visão (só no modo painel)
    if hasattr(servico, "receber_quadro"):
        app.include_router(criar_rotas_agente(banco, servico, push, notificador_remoto, pasta_fotos))

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
        if exigir_login and not await asyncio.to_thread(usuario_da_conexao, ws):
            await ws.close(code=4401)  # sem sessão válida: a conexão é recusada
            return
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
