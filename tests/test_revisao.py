"""
Testes das correções da revisão de segurança e desempenho (cache de sessão, limite por IP, origem do WebSocket,
câmera do navegador sem administrador, revogação imediata com cache de chaves, status compartilhado).
"""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from sentinela_api import agentes  # noqa: E402
from sentinela_api import autenticacao as auth  # noqa: E402
from sentinela_api.app import criar_app  # noqa: E402
from sentinela_api.banco import Banco  # noqa: E402
from sentinela_api.servico_visao import ServicoRemoto  # noqa: E402

SENHA = "uma-senha-bem-longa-1"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


@pytest.fixture
def painel(tmp_path):
    """Modo painel (VPS) com login obrigatório, um admin e uma cuidadora."""
    banco = Banco(str(tmp_path / "p.db"), usar_postgres=False)
    limitador_ip = auth.LimitadorLogin(max_erros=4, bloqueio_s=60)
    app = criar_app(banco, ServicoRemoto(banco), None, None, exigir_login=True,
                    pasta_fotos=str(tmp_path / "fotos"), limitador_ip=limitador_ip)
    banco.criar_usuario("admin", "Administrador", auth.hash_senha(SENHA), "ADMIN")
    banco.criar_usuario("maria", "Maria", auth.hash_senha(SENHA), "CUIDADOR")
    return banco, app


def _logado(app, usuario):
    cliente = TestClient(app)
    assert cliente.post("/api/login", json={"usuario": usuario, "senha": SENHA}).status_code == 200
    return cliente


def test_logout_vale_na_hora_mesmo_com_cache_de_sessao(painel):
    _, app = painel
    cliente = _logado(app, "maria")
    assert cliente.get("/api/alertas").status_code == 200  # sessão entra no cache
    token = cliente.cookies.get("sentinela_sessao")
    cliente.post("/api/logout")
    outro = TestClient(app)
    outro.cookies.set("sentinela_sessao", token)  # alguém tentando reaproveitar o cookie antigo
    assert outro.get("/api/alertas").status_code == 401


def test_desativar_usuario_derruba_a_sessao_na_hora(painel):
    banco, app = painel
    maria = _logado(app, "maria")
    assert maria.get("/api/alertas").status_code == 200
    admin = _logado(app, "admin")
    id_maria = next(u["id"] for u in banco.listar_usuarios() if u["usuario"] == "maria")
    assert admin.patch(f"/api/usuarios/{id_maria}", json={"ativo": False}).status_code == 200
    assert maria.get("/api/alertas").status_code == 401


def test_limite_por_ip_bloqueia_senhas_em_usuarios_diferentes(painel):
    _, app = painel
    cliente = TestClient(app)
    for usuario in ("ana", "bia", "caio", "duda"):  # 4 erros, cada um num usuário diferente
        assert cliente.post("/api/login", json={"usuario": usuario, "senha": "errada"}).status_code == 401
    # o 5º pedido do mesmo IP é recusado antes de conferir a senha, mesmo sendo a senha certa
    assert cliente.post("/api/login", json={"usuario": "maria", "senha": SENHA}).status_code == 429


def test_websocket_de_outro_site_e_recusado(painel):
    _, app = painel
    cliente = _logado(app, "maria")
    with pytest.raises(WebSocketDisconnect) as erro:
        with cliente.websocket_connect("/api/ws", headers={"origin": "https://site-malicioso.com"}) as ws:
            ws.receive_json()
    assert erro.value.code == 4403
    with cliente.websocket_connect("/api/ws", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_json()["tipo"] == "status"


def test_cuidadora_liga_a_camera_do_proprio_aparelho_sem_ser_admin(painel):
    banco, app = painel
    maria = _logado(app, "maria")
    assert maria.post("/api/agentes", json={"nome": "X"}).status_code == 403  # criar agente qualquer: só admin
    r = maria.post("/api/agentes/navegador", json={"aparelho": "abc123def456ghi7", "nome": "Quarto 2"})
    assert r.status_code == 201 and r.json()["token"].startswith("snt_")
    # outro aparelho com o MESMO nome de câmera ganha outro agente: um não derruba o outro
    r2 = maria.post("/api/agentes/navegador", json={"aparelho": "zzz999yyy888xxx7", "nome": "Quarto 2"})
    assert r2.json()["id"] != r.json()["id"]
    # o mesmo aparelho religando a câmera reaproveita o agente dele (com chave nova)
    r3 = maria.post("/api/agentes/navegador", json={"aparelho": "abc123def456ghi7", "nome": "Quarto 2"})
    assert r3.json()["id"] == r.json()["id"] and r3.json()["token"] != r.json()["token"]
    # desligar a câmera revoga a chave dela
    assert maria.post("/api/agentes/navegador/abc123def456ghi7/encerrar").status_code == 204
    cab = {"Authorization": f"Bearer {r3.json()['token']}"}
    assert TestClient(app).post("/api/agente/camera", json={"nome": "Q"}, headers=cab).status_code == 401


def test_revogar_pela_tela_vale_na_hora_apesar_do_cache_de_chaves(painel):
    banco, app = painel
    token = agentes.novo_token()
    banco.criar_agente("Sala", agentes.hash_token(token))
    agente_http = TestClient(app)
    cab = {"Authorization": f"Bearer {token}"}
    camera = agente_http.post("/api/agente/camera", json={"nome": "Sala"}, headers=cab).json()
    url = f"/api/agente/quadro?camera_id={camera['id']}"
    assert agente_http.post(url, content=JPEG, headers={**cab, "Content-Type": "image/jpeg"}).status_code == 200
    admin = _logado(app, "admin")
    id_agente = banco.listar_agentes()[0]["id"]
    assert admin.patch(f"/api/agentes/{id_agente}", json={"ativo": False}).status_code == 200
    assert agente_http.post(url, content=JPEG, headers={**cab, "Content-Type": "image/jpeg"}).status_code == 401


def test_quadro_grande_e_recusado_pelo_tamanho_antes_de_ler(painel):
    banco, app = painel
    token = agentes.novo_token()
    banco.criar_agente("Sala", agentes.hash_token(token))
    http = TestClient(app)
    cab = {"Authorization": f"Bearer {token}"}
    camera = http.post("/api/agente/camera", json={"nome": "Sala"}, headers=cab).json()
    grande = b"\xff\xd8\xff" + b"0" * (700 * 1024)
    r = http.post(f"/api/agente/quadro?camera_id={camera['id']}", content=grande, headers={**cab, "Content-Type": "image/jpeg"})
    assert r.status_code == 413


def test_status_do_tempo_real_e_calculado_uma_vez_por_segundo_para_todos(painel, monkeypatch):
    banco, app = painel
    montagens = {"n": 0}
    original = banco.listar_alertas

    def contar(*a, **kw):  # o instantâneo compartilhado lista os alertas recentes 1 vez por montagem
        montagens["n"] += 1
        return original(*a, **kw)
    monkeypatch.setattr(banco, "listar_alertas", contar)
    clientes = [_logado(app, "maria") for _ in range(3)]
    sockets = [c.websocket_connect("/api/ws").__enter__() for c in clientes]
    try:
        for ws in sockets:
            assert ws.receive_json()["tipo"] == "status"
        # 3 painéis abertos no mesmo segundo: o banco foi consultado para 1 montagem, não para 3 (antes eram 6 consultas)
        assert montagens["n"] == 1
    finally:
        for ws in sockets:
            ws.__exit__(None, None, None)


def test_banco_falhando_na_hora_da_queda_o_alerta_e_gravado_depois(tmp_path):
    """Câmera local: o gravador tenta de novo; o vídeo não espera o banco e o alerta não se perde."""
    import time as relogio

    from sentinela_api.servico_visao import ServicoVisao
    from sentinela_pose.alertas import NotificadorAlertas
    from sentinela_pose.config import ConfigQueda
    from test_api import CapturaFalsa, EstimadorFalso

    banco = Banco(str(tmp_path / "local.db"), usar_postgres=False)
    camera = banco.garantir_camera("Quarto", "T", "fake")
    original = banco.registrar_alerta
    falhas = {"n": 0}

    def instavel(*a, **kw):
        if falhas["n"] < 2:
            falhas["n"] += 1
            raise ConnectionError("banco fora do ar")
        return original(*a, **kw)
    banco.registrar_alerta = instavel
    servico = ServicoVisao(banco, camera, "fake", cfg_queda=ConfigQueda(), criar_captura=CapturaFalsa,
                           criar_estimador=EstimadorFalso, desenhar=lambda q, p, f: q,
                           notificador=NotificadorAlertas(pasta=str(tmp_path / "fotos"), cooldown_s=0))
    servico.iniciar()
    try:
        limite = relogio.monotonic() + 15
        while relogio.monotonic() < limite and banco.contar_pendentes() == 0:
            relogio.sleep(0.2)
        assert falhas["n"] == 2 and banco.contar_pendentes() == 1
    finally:
        servico.parar()
