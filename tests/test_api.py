"""
Testes da API + serviço de visão SEM câmera e SEM MediaPipe.

Trocamos a captura e o estimador por versões falsas:
  - CapturaFalsa entrega quadros pretos a ~30 FPS;
  - EstimadorFalso devolve uma pose sintética que fica em pé por 1 s, cai em 0,5 s e fica deitada.
Assim o fluxo inteiro (detector -> banco -> rotas) roda como na vida real.

Rodar:  python -m pytest tests -v
"""

import math
import time

import numpy as np
import pytest

fastapi = pytest.importorskip("fastapi")  # pula se a API não estiver instalada
from fastapi.testclient import TestClient  # noqa: E402

from sentinela_api.app import criar_app  # noqa: E402
from sentinela_api.banco import Banco  # noqa: E402
from sentinela_api.sensibilidade import aplicar_sensibilidade  # noqa: E402
from sentinela_api.servico_visao import ServicoVisao  # noqa: E402
from sentinela_pose.alertas import NotificadorAlertas  # noqa: E402
from sentinela_pose.config import ConfigQueda  # noqa: E402
from sentinela_pose.pontos import OMBRO_D, OMBRO_E, QUADRIL_D, QUADRIL_E, TOTAL_PONTOS, Pose  # noqa: E402


class CapturaFalsa:
    rodando = True

    def __init__(self, _fonte):
        pass

    def ler(self):
        time.sleep(1 / 30)
        return np.zeros((360, 640, 3), dtype=np.uint8)

    def fechar(self):
        self.rodando = False


class EstimadorFalso:
    """Simula uma queda usando o relógio real (a lógica de queda é baseada em tempo)."""

    def __init__(self, _cfg):
        self.inicio = time.time()

    def processar(self, _quadro, agora):
        t = agora - self.inicio
        progresso = 0.0 if t < 1.0 else min((t - 1.0) / 0.5, 1.0)  # 0 = em pé, 1 = deitado
        angulo = math.radians(90 * progresso)
        qx, qy = 320.0, 180.0 + 120.0 * progresso
        ox, oy = qx + 80 * math.sin(angulo), qy - 80 * math.cos(angulo)
        pontos = np.zeros((TOTAL_PONTOS, 3), dtype=np.float32)
        pontos[QUADRIL_E], pontos[QUADRIL_D] = (qx - 10, qy, 1), (qx + 10, qy, 1)
        pontos[OMBRO_E], pontos[OMBRO_D] = (ox - 15, oy, 1), (ox + 15, oy, 1)
        return [Pose(pontos=pontos)]

    def fechar(self):
        pass


@pytest.fixture
def ambiente(tmp_path):
    banco = Banco(str(tmp_path / "teste.db"), usar_postgres=False)  # testes nunca tocam o banco do servidor
    camera = banco.garantir_camera("Quarto teste", "Térreo", "fake")
    servico = ServicoVisao(banco, camera, "fake", cfg_queda=ConfigQueda(),
                           criar_captura=CapturaFalsa, criar_estimador=EstimadorFalso,
                           desenhar=lambda quadro, pessoas, fps: quadro,
                           notificador=NotificadorAlertas(pasta=str(tmp_path / "alertas"), cooldown_s=0))
    cliente = TestClient(criar_app(banco, servico))
    yield banco, servico, cliente
    servico.parar()


def esperar_alerta(cliente, timeout=8.0):
    limite = time.time() + timeout
    while time.time() < limite:
        alertas = cliente.get("/api/alertas").json()
        if alertas:
            return alertas
        time.sleep(0.2)
    return []


def test_queda_simulada_vira_alerta_pendente_com_imagem(ambiente):
    _, servico, cliente = ambiente
    servico.iniciar()
    alertas = esperar_alerta(cliente)
    assert len(alertas) == 1
    assert alertas[0]["tipo"] == "QUEDA"
    assert alertas[0]["status"] == "PENDENTE"
    assert cliente.get(f"/api/alertas/{alertas[0]['id']}/imagem").status_code == 200
    assert cliente.get("/api/status").json()["pendentes"] == 1


def test_quadro_atual_e_jpeg_sem_cache(ambiente):
    _, _, cliente = ambiente
    r = cliente.get("/api/quadro")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "no-store"
    assert r.content[:2] == b"\xff\xd8"  # assinatura de arquivo JPEG


def test_tratar_alerta_registra_quem_e_quando(ambiente):
    banco, _, cliente = ambiente
    alerta = banco.registrar_alerta(1, 1, "queda", 0.9, None)
    r = cliente.patch(f"/api/alertas/{alerta['id']}", json={"status": "FALSO_ALARME", "tratado_por": "Felipe"})
    assert r.status_code == 200
    assert r.json()["status"] == "FALSO_ALARME"
    assert r.json()["tratado_por"] == "Felipe"
    assert r.json()["tratado_em"]


def test_tratar_alerta_status_invalido_e_rejeitado(ambiente):
    banco, _, cliente = ambiente
    alerta = banco.registrar_alerta(1, 1, "queda", 0.9, None)
    assert cliente.patch(f"/api/alertas/{alerta['id']}", json={"status": "PENDENTE"}).status_code == 422
    assert cliente.patch("/api/alertas/999", json={"status": "RESOLVIDO"}).status_code == 404


def test_filtro_por_tipo(ambiente):
    banco, _, cliente = ambiente
    banco.registrar_alerta(1, 1, "queda", 0.9, None)
    banco.registrar_alerta(1, 2, "pessoa_no_chao", 0.8, None)
    tipos = [a["tipo"] for a in cliente.get("/api/alertas", params={"tipo": "MOVIMENTO_ANOMALO"}).json()]
    assert tipos == ["MOVIMENTO_ANOMALO"]


def test_sensibilidade_altera_detector_ao_vivo(ambiente):
    _, servico, cliente = ambiente
    r = cliente.put("/api/configuracao", json={"sensibilidade": 1.0})
    assert r.json()["rotulo"] == "Alta (100%)"
    assert servico.cfg_queda.tempo_confirma_queda == pytest.approx(1.0)
    assert cliente.put("/api/configuracao", json={"sensibilidade": 1.5}).status_code == 422


def test_desligar_camera_pausa_servico(ambiente):
    _, servico, cliente = ambiente
    r = cliente.put("/api/cameras/1", json={"ativa": False})
    assert r.json()["ativa"] is False
    assert servico.ativa is False


def test_contatos_crud_e_validacao(ambiente):
    _, _, cliente = ambiente
    r = cliente.post("/api/contatos", json={"nome": "SAMU", "telefone": "192", "tipo": "Emergência"})
    assert r.status_code == 201
    assert cliente.post("/api/contatos", json={"nome": "X", "telefone": "abc<script>"}).status_code == 422
    assert len(cliente.get("/api/contatos").json()) == 1
    assert cliente.delete(f"/api/contatos/{r.json()['id']}").status_code == 204
    assert cliente.get("/api/contatos").json() == []


def test_websocket_envia_status_e_alerta_novo(ambiente):
    banco, _, cliente = ambiente
    with cliente.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["tipo"] == "status"
        banco.registrar_alerta(1, 1, "queda", 0.9, None)
        mensagens = [ws.receive_json() for _ in range(2)]
        assert any(m["tipo"] == "alerta" and m["alerta"]["tipo"] == "QUEDA" for m in mensagens)


@pytest.mark.parametrize("s,angulo", [(0.0, 70.0), (1.0, 50.0)])
def test_mapeamento_sensibilidade(s, angulo):
    assert aplicar_sensibilidade(ConfigQueda(), s).angulo_deitado == pytest.approx(angulo)


# ------------------------------------------------------------------ Web Push
def test_assinatura_push_e_envio_ao_registrar_alerta(ambiente):
    from sentinela_api.push import ServicoPush, gerar_chaves

    banco, servico, cliente = ambiente
    chaves = gerar_chaves()
    enviados = []
    push = ServicoPush(banco, chaves["VAPID_PUBLIC_KEY"], chaves["VAPID_PRIVATE_KEY"],
                       enviar_fn=lambda **kw: enviados.append(kw))

    app_push = TestClient(criar_app(banco, servico, None, push))
    assert app_push.get("/api/push/chave").json() == {"chave": chaves["VAPID_PUBLIC_KEY"]}

    corpo = {"endpoint": "https://push.exemplo/abc123", "keys": {"p256dh": "chave", "auth": "segredo"}}
    assert app_push.post("/api/push/assinaturas", json=corpo).status_code == 204
    assert app_push.post("/api/push/assinaturas", json=corpo).status_code == 204  # repetir não duplica
    assert len(banco.listar_assinaturas()) == 1

    alerta = banco.registrar_alerta(1, 1, "queda", 0.9, None)
    push._enviar_para_todos(alerta)
    assert len(enviados) == 1 and "Queda detectada" in enviados[0]["data"]

    assert app_push.request("DELETE", "/api/push/assinaturas", json={"endpoint": corpo["endpoint"]}).status_code == 204
    assert banco.listar_assinaturas() == []


def test_push_sem_chaves_responde_503(ambiente):
    _, _, cliente = ambiente
    assert cliente.get("/api/push/chave").status_code == 503


def test_assinatura_exige_https(ambiente):
    banco, servico, _ = ambiente
    from sentinela_api.push import ServicoPush
    app_push = TestClient(criar_app(banco, servico, None, ServicoPush(banco, "a", "b")))
    ruim = {"endpoint": "http://inseguro.exemplo/x", "keys": {"p256dh": "k", "auth": "a"}}
    assert app_push.post("/api/push/assinaturas", json=ruim).status_code == 422


# ------------------------------------------------------------------ Push confiável: envios, aparelhos, contato VAPID
def _assinatura(sufixo="1", nome=None):
    corpo = {"endpoint": f"https://push.exemplo/{sufixo}", "keys": {"p256dh": "chave", "auth": "segredo"}}
    if nome:
        corpo["nome"] = nome
    return corpo


def test_contato_vapid_padrao_e_valido_para_a_apple(ambiente, monkeypatch):
    from sentinela_api.push import ServicoPush

    banco, _, _ = ambiente
    monkeypatch.delenv("VAPID_CONTATO", raising=False)
    assert ServicoPush(banco, "a", "b")._contato == "mailto:admin@example.com"


def test_envio_ok_e_falha_ficam_registrados(ambiente):
    from sentinela_api.push import ServicoPush

    banco, servico, _ = ambiente
    banco.salvar_assinatura("https://push.exemplo/ok", "k", "a", "Aparelho OK")
    resultados = {"https://push.exemplo/ok": None}

    def enviar(subscription_info, **_):
        erro = resultados[subscription_info["endpoint"]]
        if erro:
            raise erro

    push = ServicoPush(banco, "a", "b", enviar_fn=enviar)
    push._espera_retentativa_s = 0
    alerta = banco.registrar_alerta(1, 1, "queda", 0.9, None)
    push._enviar_para_todos(alerta)
    assert [e["resultado"] for e in banco.listar_envios_push()] == ["OK"]

    resultados["https://push.exemplo/ok"] = RuntimeError("rede caiu")
    push._enviar_para_todos(alerta)
    ultimo = banco.listar_envios_push()[0]
    assert ultimo["resultado"] == "FALHA" and "rede caiu" in ultimo["detalhe"]
    aparelho = banco.listar_aparelhos()[0]
    assert aparelho["nome"] == "Aparelho OK" and aparelho["ultimo_resultado"] == "FALHA"


def test_envio_tenta_de_novo_uma_vez(ambiente):
    from sentinela_api.push import ServicoPush

    banco, _, _ = ambiente
    banco.salvar_assinatura("https://push.exemplo/r", "k", "a")
    chamadas = []

    def enviar(**_):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("falha passageira")

    push = ServicoPush(banco, "a", "b", enviar_fn=enviar)
    push._espera_retentativa_s = 0
    push._enviar_para_todos(banco.registrar_alerta(1, 1, "queda", 0.9, None))
    assert len(chamadas) == 2
    assert banco.listar_envios_push()[0]["resultado"] == "OK"


def test_aparelho_expirado_410_e_removido(ambiente):
    from sentinela_api.push import ServicoPush

    banco, _, _ = ambiente
    banco.salvar_assinatura("https://push.exemplo/velho", "k", "a")

    class Expirou(Exception):
        class response:  # noqa: N801
            status_code = 410

    def enviar(**_):
        raise Expirou()

    push = ServicoPush(banco, "a", "b", enviar_fn=enviar)
    push._enviar_para_todos(banco.registrar_alerta(1, 1, "queda", 0.9, None))
    assert banco.listar_assinaturas() == []


def test_api_lista_renomeia_e_remove_aparelhos(ambiente):
    banco, _, cliente = ambiente
    assert cliente.post("/api/push/assinaturas", json=_assinatura("a", "iPhone")).status_code == 204
    assert cliente.post("/api/push/assinaturas", json=_assinatura("b")).status_code == 204
    lista = cliente.get("/api/push/aparelhos").json()
    assert [a["nome"] for a in lista] == ["iPhone", None]
    assert "endpoint" not in lista[0] and "auth" not in lista[0]  # segredos não vão para a tela

    assert cliente.patch(f"/api/push/aparelhos/{lista[1]['id']}", json={"nome": "Tablet"}).status_code == 200
    assert cliente.patch("/api/push/aparelhos/999", json={"nome": "x"}).status_code == 404

    assert cliente.delete(f"/api/push/aparelhos/{lista[0]['id']}").status_code == 204
    assert cliente.delete(f"/api/push/aparelhos/{lista[0]['id']}").status_code == 404
    assert [a["nome"] for a in cliente.get("/api/push/aparelhos").json()] == ["Tablet"]
    assert cliente.get("/api/push/envios").status_code == 200


def test_banco_antigo_ganha_coluna_nome(tmp_path):
    import sqlite3

    caminho = str(tmp_path / "antigo.db")
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE assinatura_push (id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT NOT NULL UNIQUE, "
                "p256dh VARCHAR(255) NOT NULL, auth VARCHAR(255) NOT NULL, criada_em TIMESTAMP NOT NULL)")
    con.execute("INSERT INTO assinatura_push (endpoint, p256dh, auth, criada_em) VALUES ('https://x/1', 'k', 'a', '2026-01-01')")
    con.commit()
    con.close()

    banco = Banco(caminho, usar_postgres=False)  # migra sem perder o aparelho já cadastrado
    assert banco.listar_aparelhos()[0]["nome"] is None
    banco.renomear_aparelho(1, "Celular")
    assert banco.listar_aparelhos()[0]["nome"] == "Celular"


# ------------------------------------------------------------------ Login, papéis e sessão
SENHA = "uma-senha-bem-longa-1"


@pytest.fixture
def ambiente_login(tmp_path):
    from sentinela_api import autenticacao as auth

    banco = Banco(str(tmp_path / "login.db"), usar_postgres=False)
    camera = banco.garantir_camera("Quarto teste", "Térreo", "fake")
    servico = ServicoVisao(banco, camera, "fake", cfg_queda=ConfigQueda(),
                           criar_captura=CapturaFalsa, criar_estimador=EstimadorFalso,
                           desenhar=lambda quadro, pessoas, fps: quadro,
                           notificador=NotificadorAlertas(pasta=str(tmp_path / "alertas"), cooldown_s=0))
    relogio = [0.0]
    limitador = auth.LimitadorLogin(max_erros=3, bloqueio_s=60, agora=lambda: relogio[0])
    app = criar_app(banco, servico, None, None, exigir_login=True, limitador=limitador)
    banco.criar_usuario("admin", "Administrador", auth.hash_senha(SENHA), "ADMIN")
    banco.criar_usuario("maria", "Maria Cuidadora", auth.hash_senha(SENHA), "CUIDADOR")
    yield banco, app, relogio
    servico.parar()


def _entrar(app, usuario, senha=SENHA):
    cliente = TestClient(app)
    resposta = cliente.post("/api/login", json={"usuario": usuario, "senha": senha})
    return cliente, resposta


def test_sem_login_a_api_responde_401_mas_eu_informa(ambiente_login):
    _, app, _ = ambiente_login
    anonimo = TestClient(app)
    assert anonimo.get("/api/status").status_code == 401
    assert anonimo.get("/api/alertas").status_code == 401
    assert anonimo.get("/api/video").status_code == 401
    assert anonimo.get("/api/eu").json() == {"login_obrigatorio": True, "usuario": None}


def test_login_cookie_httponly_sessao_e_logout(ambiente_login):
    banco, app, _ = ambiente_login
    cliente, resposta = _entrar(app, "maria")
    assert resposta.status_code == 200 and resposta.json()["papel"] == "CUIDADOR"
    cookie = resposta.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert cliente.get("/api/status").status_code == 200
    assert cliente.get("/api/eu").json()["usuario"]["usuario"] == "maria"

    token = cliente.cookies.get("sentinela_sessao")
    assert token not in str(banco._consultar("SELECT token_hash FROM sessao"))  # o banco guarda só o hash

    assert cliente.post("/api/logout").status_code == 204
    assert cliente.get("/api/status").status_code == 401


def test_login_errado_nao_revela_se_o_usuario_existe(ambiente_login):
    _, app, _ = ambiente_login
    _, senha_errada = _entrar(app, "maria", "senha-errada-123")
    _, sem_usuario = _entrar(app, "fantasma", "senha-errada-123")
    assert senha_errada.status_code == sem_usuario.status_code == 401
    assert senha_errada.json() == sem_usuario.json()


def test_bloqueia_apos_erros_seguidos_e_libera_depois(ambiente_login):
    _, app, relogio = ambiente_login
    for _ in range(3):
        assert _entrar(app, "maria", "errada-errada-1")[1].status_code == 401
    _, bloqueado = _entrar(app, "maria")  # até a senha certa é recusada durante o bloqueio
    assert bloqueado.status_code == 429 and "retry-after" in bloqueado.headers
    relogio[0] = 61
    assert _entrar(app, "maria")[1].status_code == 200


def test_usuario_desativado_perde_a_sessao_e_nao_entra(ambiente_login):
    banco, app, _ = ambiente_login
    admin, _ = _entrar(app, "admin")
    maria, _ = _entrar(app, "maria")
    maria_id = banco.obter_usuario_para_login("maria")["id"]
    assert admin.patch(f"/api/usuarios/{maria_id}", json={"ativo": False}).status_code == 200
    assert maria.get("/api/status").status_code == 401
    assert _entrar(app, "maria")[1].status_code == 401


def test_cuidador_nao_altera_configuracao_nem_gerencia_usuarios(ambiente_login):
    banco, app, _ = ambiente_login
    maria, _ = _entrar(app, "maria")
    assert maria.get("/api/configuracao").status_code == 200
    assert maria.put("/api/configuracao", json={"sensibilidade": 0.5}).status_code == 403
    assert maria.post("/api/contatos", json={"nome": "X", "telefone": "123"}).status_code == 403
    assert maria.get("/api/usuarios").status_code == 403
    assert maria.get("/api/push/aparelhos").status_code == 403

    alerta = banco.registrar_alerta(1, 1, "queda", 0.9, None)
    tratado = maria.patch(f"/api/alertas/{alerta['id']}", json={"status": "RESOLVIDO", "tratado_por": "Outro Nome"})
    assert tratado.status_code == 200
    assert tratado.json()["tratado_por"] == "Maria Cuidadora"  # vem da sessão, não do texto enviado

    admin, _ = _entrar(app, "admin")
    assert admin.put("/api/configuracao", json={"sensibilidade": 0.5}).status_code == 200
    assert admin.get("/api/usuarios").status_code == 200
    assert "senha_hash" not in admin.get("/api/usuarios").text


def test_admin_cria_usuario_com_regras_de_senha(ambiente_login):
    _, app, _ = ambiente_login
    admin, _ = _entrar(app, "admin")
    base = {"usuario": "joao", "nome": "João", "papel": "CUIDADOR"}
    assert admin.post("/api/usuarios", json={**base, "senha": "curta"}).status_code == 422
    assert admin.post("/api/usuarios", json={**base, "senha": SENHA}).status_code == 201
    assert admin.post("/api/usuarios", json={**base, "senha": SENHA}).status_code == 409
    assert admin.post("/api/usuarios", json={**base, "usuario": "Com Espaço", "senha": SENHA}).status_code == 422
    assert _entrar(app, "joao")[1].status_code == 200
    assert admin.patch("/api/usuarios/1", json={"ativo": False}).status_code == 400  # não se desativa sozinho


def test_troca_de_senha_encerra_as_sessoes(ambiente_login):
    banco, app, _ = ambiente_login
    admin, _ = _entrar(app, "admin")
    maria, _ = _entrar(app, "maria")
    maria_id = banco.obter_usuario_para_login("maria")["id"]
    assert admin.patch(f"/api/usuarios/{maria_id}", json={"senha": "outra-senha-longa-9"}).status_code == 200
    assert maria.get("/api/status").status_code == 401
    assert _entrar(app, "maria", "outra-senha-longa-9")[1].status_code == 200


def test_origem_diferente_em_escrita_e_recusada(ambiente_login):
    _, app, _ = ambiente_login
    maria, _ = _entrar(app, "maria")
    cabecalho = {"Origin": "https://site-malicioso.exemplo"}
    assert maria.patch("/api/alertas/1", json={"status": "RESOLVIDO"}, headers=cabecalho).status_code == 403
    assert maria.get("/api/status", headers=cabecalho).status_code == 200  # leitura não é afetada


def test_websocket_exige_sessao(ambiente_login):
    from starlette.websockets import WebSocketDisconnect

    _, app, _ = ambiente_login
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/api/ws"):
            pass
    maria, _ = _entrar(app, "maria")
    with maria.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["tipo"] == "status"


def test_sessao_expirada_nao_vale(ambiente_login):
    banco, app, _ = ambiente_login
    maria, _ = _entrar(app, "maria")
    banco._executar("UPDATE sessao SET expira_em = ?", ("2000-01-01T00:00:00",))
    assert maria.get("/api/status").status_code == 401


def test_cli_cria_usuario_pedindo_a_senha_no_terminal(tmp_path, monkeypatch, capsys):
    from sentinela_api import usuarios

    banco = Banco(str(tmp_path / "cli.db"), usar_postgres=False)
    respostas = iter(["curta", "uma-senha-bem-longa-1", "uma-senha-bem-longa-1"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(respostas))
    assert usuarios.main(["criar", "--usuario", "ana", "--nome", "Ana", "--papel", "ADMIN"], banco) == 0
    assert "pelo menos" in capsys.readouterr().out  # a 1ª senha, curta demais, foi recusada
    assert banco.obter_usuario_para_login("ana")["papel"] == "ADMIN"
    assert usuarios.main(["criar", "--usuario", "ana"], banco) == 1  # duplicado
    assert usuarios.main(["desativar", "--usuario", "ana"], banco) == 0
    assert banco.obter_usuario_para_login("ana")["ativo"] is False


def test_hash_de_senha():
    from sentinela_api import autenticacao as auth

    h = auth.hash_senha(SENHA)
    assert SENHA not in h and h.startswith("scrypt$")
    assert auth.hash_senha(SENHA) != h  # sal aleatório
    assert auth.verificar_senha(SENHA, h) and not auth.verificar_senha("outra", h)
    assert not auth.verificar_senha(SENHA, "lixo") and not auth.verificar_senha(SENHA, "scrypt$a$b$c$d$e")
# ------------------------------------------------- aviso ao notificador de WhatsApp (outro servidor)
def test_notificador_remoto_envia_post_com_token():
    import threading
    from sentinela_api.notificador_remoto import NotificadorRemoto

    chamadas, pronto = [], threading.Event()

    class Resposta:
        status_code = 202

    def falso_post(url, json, headers, timeout):
        chamadas.append((url, json, headers))
        pronto.set()
        return Resposta()

    n = NotificadorRemoto("http://zap:8100/", "tok", enviar=falso_post)
    n.avisar({"id": 42})
    assert pronto.wait(2)
    assert chamadas == [("http://zap:8100/notificar", {"alerta_id": 42}, {"Authorization": "Bearer tok"})]


def test_notificador_remoto_sem_configuracao_nao_chama():
    from sentinela_api.notificador_remoto import NotificadorRemoto

    def falso_post(*a, **k):
        raise AssertionError("não deveria chamar")

    n = NotificadorRemoto("", "", enviar=falso_post)
    assert not n.configurado
    n.avisar({"id": 1})


def test_notificador_remoto_fora_do_ar_nao_derruba():
    import requests
    from sentinela_api.notificador_remoto import NotificadorRemoto

    def falso_post(*a, **k):
        raise requests.ConnectionError("sem rede")

    NotificadorRemoto("http://zap:8100", "tok", enviar=falso_post)._post(5)  # só registra no log
