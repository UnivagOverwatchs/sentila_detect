"""
Testes de várias câmeras: quadro e estado por câmera, e chaves de agente criadas pelo painel (administrador).

Rodar:  python -m pytest tests/test_cameras.py -v
"""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sentinela_api import agentes, autenticacao as auth  # noqa: E402
from sentinela_api.app import criar_app  # noqa: E402
from sentinela_api.banco import Banco  # noqa: E402
from sentinela_api.servico_visao import ServicoRemoto  # noqa: E402

JPEG_A = b"\xff\xd8\xff\xe0" + b"A" * 40 + b"\xff\xd9"
JPEG_B = b"\xff\xd8\xff\xe0" + b"B" * 40 + b"\xff\xd9"
SENHA = "uma-senha-bem-longa-1"


def _cab(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def painel(tmp_path):
    banco = Banco(str(tmp_path / "cams.db"), usar_postgres=False)
    servico = ServicoRemoto(banco)
    token = agentes.novo_token()
    banco.criar_agente("Casa", agentes.hash_token(token))
    app = criar_app(banco, servico, None, None, pasta_fotos=str(tmp_path / "fotos"))
    return banco, servico, TestClient(app), token


def _camera(cliente, token, nome):
    r = cliente.post("/api/agente/camera", json={"nome": nome, "local": "Casa"}, headers=_cab(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ------------------------------------------------------------------ vários quadros e estados
def test_cada_camera_tem_o_seu_quadro(painel):
    _, _, cliente, token = painel
    a, b = _camera(cliente, token, "Sala"), _camera(cliente, token, "Quarto")
    cliente.post("/api/agente/quadro", params={"camera_id": a}, content=JPEG_A, headers=_cab(token))
    cliente.post("/api/agente/quadro", params={"camera_id": b}, content=JPEG_B, headers=_cab(token))
    assert cliente.get("/api/quadro", params={"camera_id": a}).content == JPEG_A
    assert cliente.get("/api/quadro", params={"camera_id": b}).content == JPEG_B
    assert cliente.get("/api/quadro").content == JPEG_B  # sem camera_id: a que falou por último, como antes


def test_camera_sem_noticias_mostra_o_aviso_e_nao_o_quadro_de_outra(painel):
    _, _, cliente, token = painel
    a, b = _camera(cliente, token, "Sala"), _camera(cliente, token, "Quarto")
    cliente.post("/api/agente/quadro", params={"camera_id": a}, content=JPEG_A, headers=_cab(token))
    assert cliente.get("/api/quadro", params={"camera_id": b}).content not in (JPEG_A, JPEG_B)


def test_status_traz_o_estado_de_todas_as_cameras(painel):
    banco, servico, cliente, token = painel
    antiga = banco.garantir_camera("Câmera antiga", "Térreo", "0")["id"]  # grava direto no banco: sem agente
    a, b = _camera(cliente, token, "Sala"), _camera(cliente, token, "Quarto")
    cliente.post("/api/agente/status", headers=_cab(token), json={"camera_id": a, "fps": 10, "pessoas": 2, "estado": "atencao"})
    cliente.post("/api/agente/status", headers=_cab(token), json={"camera_id": b, "fps": 5, "pessoas": 0})
    cameras = {c["id"]: c for c in cliente.get("/api/status").json()["cameras"]}
    assert cameras[a]["online"] is True and cameras[a]["pessoas"] == 2 and cameras[a]["estado"] == "atencao"
    assert cameras[b]["online"] is True and cameras[b]["fps"] == 5
    assert cameras[antiga]["online"] is None  # ninguém avisa por ela: a tela mostra "sem agente", não "offline"
    assert {c["nome"] for c in cameras.values()} == {"Câmera antiga", "Sala", "Quarto"}


def test_so_a_camera_que_calou_fica_offline(painel):
    _, servico, cliente, token = painel
    a, b = _camera(cliente, token, "Sala"), _camera(cliente, token, "Quarto")
    for cam in (a, b):
        cliente.post("/api/agente/status", headers=_cab(token), json={"camera_id": cam, "fps": 8})
    servico._visto[a] -= ServicoRemoto.AGENTE_ONLINE_S + 1
    cameras = {c["id"]: c for c in cliente.get("/api/status").json()["cameras"]}
    assert cameras[a]["online"] is False and cameras[a]["estado"] == "normal"
    assert cameras[b]["online"] is True


def test_servico_local_de_uma_camera_tambem_informa_o_estado(tmp_path):
    """O modo antigo (servidor.py com a webcam) continua entregando o mesmo formato à interface."""
    from test_api import CapturaFalsa, EstimadorFalso  # noqa: F401  (só para garantir o mesmo ambiente de teste)
    from sentinela_api.servico_visao import ServicoVisao
    from sentinela_pose.alertas import NotificadorAlertas
    from sentinela_pose.config import ConfigQueda

    banco = Banco(str(tmp_path / "local.db"), usar_postgres=False)
    camera = banco.garantir_camera("Webcam", "Sala", "0")
    banco.garantir_camera("Outra", "Sala", "1")
    servico = ServicoVisao(banco, camera, "0", cfg_queda=ConfigQueda(), criar_captura=CapturaFalsa,
                           criar_estimador=EstimadorFalso, desenhar=lambda q, p, f: q,
                           notificador=NotificadorAlertas(pasta=str(tmp_path / "a"), cooldown_s=0))
    estados = {c["nome"]: c for c in servico.estado_cameras()}
    assert estados["Webcam"]["online"] is not None and estados["Outra"]["online"] is None
    assert servico.jpeg_da_camera(camera["id"])[:2] == b"\xff\xd8"
    assert servico.jpeg_da_camera(9999)[:2] == b"\xff\xd8"  # câmera que não é deste serviço: aviso, nunca erro


# ------------------------------------------------------------------ chaves de agente criadas pelo painel
@pytest.fixture
def painel_com_login(tmp_path):
    banco = Banco(str(tmp_path / "login.db"), usar_postgres=False)
    servico = ServicoRemoto(banco)
    app = criar_app(banco, servico, None, None, exigir_login=True, pasta_fotos=str(tmp_path / "f"))
    banco.criar_usuario("admin", "Administrador", auth.hash_senha(SENHA), "ADMIN")
    banco.criar_usuario("maria", "Maria", auth.hash_senha(SENHA), "CUIDADOR")

    def entrar(usuario):
        cliente = TestClient(app)
        assert cliente.post("/api/login", json={"usuario": usuario, "senha": SENHA}).status_code == 200
        return cliente

    return banco, app, entrar


def test_admin_cria_agente_e_a_chave_aparece_uma_vez(painel_com_login):
    banco, app, entrar = painel_com_login
    admin = entrar("admin")
    r = admin.post("/api/agentes", json={"nome": "Casa da Anni"})
    assert r.status_code == 201
    token = r.json()["token"]
    assert token.startswith("snt_") and "token_hash" not in r.json()
    assert token not in str(banco._consultar("SELECT * FROM agente"))        # o banco guarda só o hash
    listado = admin.get("/api/agentes")
    assert listado.status_code == 200 and token not in listado.text           # nunca mais mostrada
    assert [a["nome"] for a in listado.json()] == ["Casa da Anni"]
    # a chave criada pelo painel realmente funciona no agente
    agente = TestClient(app)
    assert agente.post("/api/agente/camera", json={"nome": "Sala"}, headers=_cab(token)).status_code == 200


def test_cuidador_nao_mexe_nas_chaves_de_agente(painel_com_login):
    _, _, entrar = painel_com_login
    maria = entrar("maria")
    assert maria.get("/api/agentes").status_code == 403
    assert maria.post("/api/agentes", json={"nome": "X"}).status_code == 403
    assert maria.patch("/api/agentes/1", json={"ativo": False}).status_code == 403
    assert TestClient(painel_com_login[1]).get("/api/agentes").status_code == 401  # sem login: nem chega


def test_nome_de_agente_repetido_ou_invalido_e_recusado(painel_com_login):
    _, _, entrar = painel_com_login
    admin = entrar("admin")
    assert admin.post("/api/agentes", json={"nome": "Casa"}).status_code == 201
    assert admin.post("/api/agentes", json={"nome": "Casa"}).status_code == 409
    for ruim in ("", "../../etc", "a" * 81, "nome; drop table"):
        assert admin.post("/api/agentes", json={"nome": ruim}).status_code == 422, ruim


def test_nova_chave_invalida_a_antiga_e_revogar_corta_o_acesso(painel_com_login):
    _, app, entrar = painel_com_login
    admin, agente = entrar("admin"), TestClient(app)
    criado = admin.post("/api/agentes", json={"nome": "Casa"}).json()
    antiga = criado["token"]
    nova = admin.post(f"/api/agentes/{criado['id']}/nova-chave").json()["token"]
    assert nova != antiga
    assert agente.post("/api/agente/camera", json={"nome": "S"}, headers=_cab(antiga)).status_code == 401
    assert agente.post("/api/agente/camera", json={"nome": "S"}, headers=_cab(nova)).status_code == 200

    assert admin.patch(f"/api/agentes/{criado['id']}", json={"ativo": False}).json()["ativo"] is False
    assert agente.post("/api/agente/camera", json={"nome": "S"}, headers=_cab(nova)).status_code == 401
    assert admin.patch(f"/api/agentes/{criado['id']}", json={"ativo": True}).json()["ativo"] is True
    assert agente.post("/api/agente/camera", json={"nome": "S"}, headers=_cab(nova)).status_code == 200
    assert admin.post("/api/agentes/999/nova-chave").status_code == 404


# ------------------------------------------------------------------ vídeo ao vivo: ritmo conforme há espectador
def test_painel_avisa_o_agente_quando_alguem_esta_assistindo(painel):
    _, servico, cliente, token = painel
    cam = _camera(cliente, token, "Sala")
    enviar = lambda: cliente.post("/api/agente/quadro", params={"camera_id": cam}, content=JPEG_A, headers=_cab(token)).json()
    assert enviar() == {"assistindo": False}
    cliente.get("/api/quadro", params={"camera_id": cam})  # alguém abriu o vídeo no painel
    assert enviar() == {"assistindo": True}
    servico._espectador[cam] -= ServicoRemoto.ESPECTADOR_S + 1  # parou de olhar há mais de 6 s
    assert enviar() == {"assistindo": False}


def test_espectador_de_uma_camera_nao_conta_para_a_outra(painel):
    _, _, cliente, token = painel
    a, b = _camera(cliente, token, "Sala"), _camera(cliente, token, "Quarto")
    cliente.get("/api/quadro", params={"camera_id": a})
    resposta = lambda cam: cliente.post("/api/agente/quadro", params={"camera_id": cam}, content=JPEG_A, headers=_cab(token)).json()
    assert resposta(a) == {"assistindo": True} and resposta(b) == {"assistindo": False}


def test_camera_so_video_aparece_sem_deteccao_no_painel(painel):
    _, _, cliente, token = painel
    sala, navegador = _camera(cliente, token, "Sala"), _camera(cliente, token, "Celular")
    cliente.post("/api/agente/status", headers=_cab(token), json={"camera_id": sala, "fps": 10})
    cliente.post("/api/agente/status", headers=_cab(token), json={"camera_id": navegador, "fps": 6, "deteccao": False})
    cameras = {c["id"]: c for c in cliente.get("/api/status").json()["cameras"]}
    assert cameras[sala]["deteccao"] is True and cameras[navegador]["deteccao"] is False  # a tela não finge que protege


def test_sincronizador_manda_mais_quadros_com_espectador_do_que_sem(painel):
    import time

    from sentinela_api.cliente_agente import Sincronizador

    class ClienteDeMentira:
        def __init__(self, assistindo):
            self.assistindo, self.quadros = assistindo, 0

        def enviar_quadro(self, camera_id, jpeg):
            self.quadros += 1
            return self.assistindo

        def enviar_status(self, *a, **k):
            pass

        def configuracao(self, *a, **k):
            return {"sensibilidade": 0.5, "ativa": True, "area_cama": []}

    class Servico:
        cfg_queda, ativa, area_cama = None, True, []

        def jpeg_atual(self):
            return JPEG_A

        def status(self):
            return {}

    def rodar(assistindo):
        cliente = ClienteDeMentira(assistindo)
        sinc = Sincronizador(cliente, Servico(), 1, fps_video=40, espera_sem_espectador_s=0.3)
        sinc.iniciar()
        time.sleep(0.9)
        sinc.parar()
        return cliente.quadros

    com, sem = rodar(True), rodar(False)
    assert com >= 15          # ~40 por segundo pedidos: acompanha com folga para a máquina de teste
    assert sem <= 5           # ~3 por segundo: poupa a internet quando ninguém está olhando
    assert com > 3 * sem


# ------------------------------------------------------------------ excluir câmera
def test_excluir_camera_apaga_historico_e_foto_e_mantem_as_outras(painel, tmp_path):
    banco, servico, cliente, token = painel
    a, b = _camera(cliente, token, "Sala"), _camera(cliente, token, "Quarto")
    foto = tmp_path / "fotos" / "a.jpg"
    foto.parent.mkdir(exist_ok=True)
    foto.write_bytes(b"x")
    fora = tmp_path / "fora.jpg"  # fora da pasta de fotos: nunca pode ser apagada
    fora.write_bytes(b"x")
    banco.registrar_alerta(a, 1, "queda", 0.9, str(foto))
    banco.registrar_alerta(a, 2, "queda", 0.9, str(fora))
    banco.registrar_alerta(b, 1, "queda", 0.9, None)
    cliente.post("/api/agente/quadro", params={"camera_id": a}, content=JPEG_A, headers=_cab(token))

    assert cliente.delete(f"/api/cameras/{a}").status_code == 204
    assert [c["id"] for c in cliente.get("/api/cameras").json()] == [b]
    assert len(cliente.get("/api/alertas").json()) == 1  # só o da outra câmera
    assert not foto.exists()
    assert fora.exists()
    assert a not in servico._quadros


def test_excluir_camera_que_nao_existe_da_404(painel):
    _, _, cliente, _ = painel
    assert cliente.delete("/api/cameras/99").status_code == 404
