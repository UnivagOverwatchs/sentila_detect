"""
Testes do agente de visão: API do painel (/api/agente/*), cliente com fila em disco e o caminho completo
detector -> agente -> painel -> banco/push. Tudo sem câmera, sem MediaPipe e sem rede (o "painel" é o TestClient).

Rodar:  python -m pytest tests/test_agente.py -v
"""

import base64
import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sentinela_api import agentes  # noqa: E402
from sentinela_api import autenticacao as auth  # noqa: E402
from sentinela_api.app import criar_app  # noqa: E402
from sentinela_api.banco import Banco  # noqa: E402
from sentinela_api.cliente_agente import BancoRemoto, ClienteAgente, Sincronizador  # noqa: E402
from sentinela_api.sensibilidade import aplicar_sensibilidade  # noqa: E402
from sentinela_api.servico_visao import ServicoRemoto, ServicoVisao  # noqa: E402
from sentinela_pose.alertas import NotificadorAlertas  # noqa: E402
from sentinela_pose.config import ConfigQueda  # noqa: E402
from test_api import CapturaFalsa, EstimadorFalso  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"  # cabeçalho JPEG mínimo: o painel só confere a assinatura


class PushFalso:
    def __init__(self):
        self.avisados = []

    def avisar(self, alerta):
        self.avisados.append(alerta)


class ZapFalso(PushFalso):
    pass


@pytest.fixture
def painel(tmp_path):
    banco = Banco(str(tmp_path / "painel.db"), usar_postgres=False)
    servico = ServicoRemoto(banco)
    push, zap = PushFalso(), ZapFalso()
    app = criar_app(banco, servico, None, push, pasta_fotos=str(tmp_path / "fotos"), notificador_remoto=zap)
    token = agentes.novo_token()
    banco.criar_agente("Quarto 1", agentes.hash_token(token))
    return banco, servico, TestClient(app), token, push, zap, tmp_path


def _cab(token):
    return {"Authorization": f"Bearer {token}"}


def _registrar_camera(cliente, token, nome="Quarto 1"):
    r = cliente.post("/api/agente/camera", json={"nome": nome, "local": "Térreo"}, headers=_cab(token))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ autenticação do agente
def test_agente_sem_chave_ou_com_chave_errada_e_recusado(painel):
    _, _, cliente, token, _, _, _ = painel
    assert cliente.post("/api/agente/camera", json={"nome": "X"}).status_code == 401
    assert cliente.post("/api/agente/camera", json={"nome": "X"}, headers=_cab("snt_errada")).status_code == 401
    assert cliente.post("/api/agente/camera", json={"nome": "X"}, headers={"Authorization": token}).status_code == 401
    assert cliente.post("/api/agente/camera", json={"nome": "X"}, headers=_cab(token)).status_code == 200


def test_agente_revogado_perde_o_acesso_e_a_chave_nao_fica_no_banco(painel):
    banco, _, cliente, token, _, _, _ = painel
    assert token not in str(banco._consultar("SELECT * FROM agente"))  # só o SHA-256 é guardado
    assert banco.definir_agente_ativo("Quarto 1", False)
    assert cliente.post("/api/agente/camera", json={"nome": "X"}, headers=_cab(token)).status_code == 401
    banco.definir_agente_ativo("Quarto 1", True)
    assert cliente.post("/api/agente/camera", json={"nome": "X"}, headers=_cab(token)).status_code == 200


def test_chave_de_agente_nao_abre_o_painel_e_cookie_nao_abre_o_agente(tmp_path):
    banco = Banco(str(tmp_path / "login.db"), usar_postgres=False)
    servico = ServicoRemoto(banco)
    app = criar_app(banco, servico, None, None, exigir_login=True, pasta_fotos=str(tmp_path / "f"))
    token = agentes.novo_token()
    banco.criar_agente("A", agentes.hash_token(token))
    banco.criar_usuario("admin", "Admin", auth.hash_senha("uma-senha-bem-longa-1"), "ADMIN")
    cliente = TestClient(app)
    assert cliente.get("/api/status", headers=_cab(token)).status_code == 401      # chave de agente não vale no painel
    assert cliente.post("/api/agente/camera", json={"nome": "A"}, headers=_cab(token)).status_code == 200
    cliente.post("/api/login", json={"usuario": "admin", "senha": "uma-senha-bem-longa-1"})
    assert cliente.get("/api/status").status_code == 200
    assert cliente.post("/api/agente/camera", json={"nome": "A"}).status_code == 401  # sessão de usuário não vale no agente


# ------------------------------------------------------------------ câmera, config, quadro, status
def test_camera_do_agente_e_config_do_painel(painel):
    banco, _, cliente, token, _, _, _ = painel
    camera = _registrar_camera(cliente, token)
    assert camera["nome"] == "Quarto 1" and 0 <= camera["sensibilidade"] <= 1
    assert _registrar_camera(cliente, token)["id"] == camera["id"]  # registrar de novo não duplica
    assert banco.url_stream_da_camera(camera["id"]).startswith("agente:")  # nenhuma URL/senha de câmera no banco

    banco.salvar_area_cama(camera["id"], [[[0.1, 0.5], [0.9, 0.5], [0.9, 0.95], [0.1, 0.95]]])
    banco.salvar_sensibilidade(0.3)
    config = cliente.get("/api/agente/config", params={"camera_id": camera["id"]}, headers=_cab(token)).json()
    assert config["sensibilidade"] == 0.3 and config["ativa"] is True and len(config["area_cama"]) == 1


def test_agente_so_mexe_nas_proprias_cameras(painel):
    banco, _, cliente, token, _, _, _ = painel
    alheia = banco.garantir_camera("Sala (antiga)", "Térreo", "0")  # câmera cadastrada por outro caminho
    assert cliente.get("/api/agente/config", params={"camera_id": alheia["id"]}, headers=_cab(token)).status_code == 404
    assert cliente.post("/api/agente/quadro", params={"camera_id": alheia["id"]}, content=JPEG,
                        headers=_cab(token)).status_code == 404
    corpo = {"camera_id": alheia["id"], "track_id": 1, "tipo": "queda", "confianca": 0.9}
    assert cliente.post("/api/agente/alertas", json=corpo, headers=_cab(token)).status_code == 404
    assert banco.contar_pendentes() == 0


def test_quadro_e_status_aparecem_no_painel(painel):
    _, _, cliente, token, _, _, _ = painel
    camera = _registrar_camera(cliente, token)
    assert cliente.get("/api/quadro").content != JPEG  # ainda é o aviso "câmera em outro computador"
    r = cliente.post("/api/agente/quadro", params={"camera_id": camera["id"]}, content=JPEG, headers=_cab(token))
    assert r.status_code == 200 and r.json() == {"assistindo": True}  # o teste acabou de abrir o vídeo: há espectador
    assert cliente.get("/api/quadro").content == JPEG
    cliente.post("/api/agente/status", headers=_cab(token),
                 json={"camera_id": camera["id"], "fps": 12.5, "pessoas": 2, "estado": "atencao"})
    status = cliente.get("/api/status").json()
    assert status["fps"] == 12.5 and status["pessoas"] == 2 and status["estado"] == "atencao"
    assert status["camera_online"] is True and status["camera_id"] == camera["id"]


def test_agente_que_some_deixa_a_camera_offline(painel):
    _, servico, cliente, token, _, _, _ = painel
    camera = _registrar_camera(cliente, token)
    cliente.post("/api/agente/status", headers=_cab(token), json={"camera_id": camera["id"], "fps": 10})
    servico._visto[camera["id"]] -= ServicoRemoto.AGENTE_ONLINE_S + 1  # simula 15 s de silêncio
    status = cliente.get("/api/status").json()
    assert status["camera_online"] is False and status["estado"] == "normal"


@pytest.mark.parametrize("corpo, codigo", [(b"nao e jpeg", 422), (b"\xff\xd8\xff" + b"0" * (700 * 1024), 413)])
def test_quadro_invalido_ou_grande_e_recusado(painel, corpo, codigo):
    _, _, cliente, token, _, _, _ = painel
    camera = _registrar_camera(cliente, token)
    r = cliente.post("/api/agente/quadro", params={"camera_id": camera["id"]}, content=corpo, headers=_cab(token))
    assert r.status_code == codigo


# ------------------------------------------------------------------ alertas e fotos
def test_alerta_do_agente_grava_foto_avisa_push_e_whatsapp(painel):
    banco, _, cliente, token, push, zap, tmp = painel
    camera = _registrar_camera(cliente, token)
    corpo = {"camera_id": camera["id"], "track_id": 7, "tipo": "queda", "confianca": 0.93,
             "imagem_jpeg_b64": base64.b64encode(JPEG).decode()}
    r = cliente.post("/api/agente/alertas", json=corpo, headers=_cab(token))
    assert r.status_code == 201
    alerta = r.json()
    assert alerta["tipo"] == "QUEDA" and alerta["status"] == "PENDENTE" and alerta["camera_nome"] == "Quarto 1"
    assert banco.contar_pendentes() == 1
    assert [a["id"] for a in push.avisados] == [alerta["id"]] and [a["id"] for a in zap.avisados] == [alerta["id"]]

    foto = cliente.get(f"/api/alertas/{alerta['id']}/imagem")  # a foto é servida pelo painel
    assert foto.status_code == 200 and foto.content == JPEG
    assert os.path.dirname(os.path.abspath(banco.obter_alerta(alerta["id"])["imagem"])) == str((tmp / "fotos").resolve())


def test_alerta_sem_foto_tambem_vale(painel):
    _, _, cliente, token, push, _, _ = painel
    camera = _registrar_camera(cliente, token)
    r = cliente.post("/api/agente/alertas", headers=_cab(token),
                     json={"camera_id": camera["id"], "track_id": 1, "tipo": "pessoa_no_chao", "confianca": 0.5})
    assert r.status_code == 201 and r.json()["tipo"] == "MOVIMENTO_ANOMALO" and len(push.avisados) == 1


@pytest.mark.parametrize("mudanca, codigo", [
    ({"tipo": "incendio"}, 422),
    ({"confianca": 1.5}, 422),
    ({"track_id": -1}, 422),
    ({"imagem_jpeg_b64": "isto nao e base64!!"}, 422),
    ({"imagem_jpeg_b64": base64.b64encode(b"texto qualquer").decode()}, 422),
    ({"imagem_jpeg_b64": base64.b64encode(b"\xff\xd8\xff" + b"0" * (2 * 1024 * 1024 + 10)).decode()}, 413),
])
def test_alerta_invalido_e_recusado_sem_gravar_nada(painel, mudanca, codigo):
    banco, _, cliente, token, push, _, tmp = painel
    camera = _registrar_camera(cliente, token)
    corpo = {"camera_id": camera["id"], "track_id": 1, "tipo": "queda", "confianca": 0.9, **mudanca}
    r = cliente.post("/api/agente/alertas", json=corpo, headers=_cab(token))
    assert r.status_code == codigo, r.text
    assert banco.contar_pendentes() == 0 and push.avisados == []


def test_nome_da_foto_e_gerado_pelo_painel(painel):
    """Nada que venha do agente entra no caminho do arquivo (sem path traversal)."""
    banco, _, cliente, token, _, _, tmp = painel
    camera = _registrar_camera(cliente, token, nome="../../etc/passwd")
    corpo = {"camera_id": camera["id"], "track_id": 1, "tipo": "queda", "confianca": 0.9,
             "imagem_jpeg_b64": base64.b64encode(JPEG).decode()}
    alerta = cliente.post("/api/agente/alertas", json=corpo, headers=_cab(token)).json()
    caminho = os.path.abspath(banco.obter_alerta(alerta["id"])["imagem"])
    assert os.path.dirname(caminho) == str((tmp / "fotos").resolve()) and ".." not in os.path.basename(caminho)


# ------------------------------------------------------------------ CLI de chaves
def test_cli_de_agentes(tmp_path, capsys):
    banco = Banco(str(tmp_path / "cli.db"), usar_postgres=False)
    assert agentes.main(["criar", "--nome", "Quarto 1"], banco) == 0
    saida = capsys.readouterr().out
    token = next(linha for linha in saida.splitlines() if linha.startswith("snt_"))
    assert banco.obter_agente_por_token(agentes.hash_token(token))["nome"] == "Quarto 1"
    assert agentes.main(["criar", "--nome", "Quarto 1"], banco) == 1            # duplicado
    assert agentes.main(["nova-chave", "--nome", "Quarto 1"], banco) == 0       # a antiga deixa de valer
    assert banco.obter_agente_por_token(agentes.hash_token(token)) is None
    assert agentes.main(["revogar", "--nome", "Quarto 1"], banco) == 0
    assert agentes.main(["revogar", "--nome", "Fantasma"], banco) == 1
    assert agentes.main(["listar"], banco) == 0 and "REVOGADO" in capsys.readouterr().out


# ------------------------------------------------------------------ cliente com fila em disco
def _cliente(painel_cliente, token):
    return ClienteAgente("http://testserver", token, sessao=painel_cliente)


def test_fila_envia_alerta_com_foto_e_apaga_a_copia_local(painel):
    banco, _, http, token, push, _, tmp = painel
    camera = _registrar_camera(http, token)
    foto = tmp / "local.jpg"
    foto.write_bytes(JPEG)
    remoto = BancoRemoto(_cliente(http, token), pasta_fila=str(tmp / "fila"))
    remoto.registrar_alerta(camera["id"], 3, "queda", 0.9, str(foto))
    assert len(remoto.pendentes()) == 1
    assert remoto.enviar_pendentes() is True
    assert remoto.pendentes() == [] and banco.contar_pendentes() == 1
    assert not foto.exists()  # a foto já está no painel: sem cópia no computador do local


def test_agente_pode_guardar_a_foto_local_se_pedido(painel):
    _, _, http, token, _, _, tmp = painel
    camera = _registrar_camera(http, token)
    foto = tmp / "guardar.jpg"
    foto.write_bytes(JPEG)
    remoto = BancoRemoto(_cliente(http, token), pasta_fila=str(tmp / "fila"), guardar_fotos=True)
    remoto.registrar_alerta(camera["id"], 3, "queda", 0.9, str(foto))
    remoto.enviar_pendentes()
    assert foto.exists()


def test_sem_rede_o_alerta_fica_na_fila_e_segue_quando_a_rede_volta(painel):
    import requests

    banco, _, http, token, _, _, tmp = painel
    camera = _registrar_camera(http, token)
    estado = {"rede": False}

    class SessaoQueFalha:
        def __getattr__(self, metodo):
            def chamar(*a, **kw):
                if not estado["rede"]:
                    raise requests.ConnectionError("sem rede")
                return getattr(http, metodo)(*a, **kw)
            return chamar

    remoto = BancoRemoto(ClienteAgente("http://testserver", token, sessao=SessaoQueFalha()), pasta_fila=str(tmp / "fila"))
    remoto.registrar_alerta(camera["id"], 1, "queda", 0.9, None)
    assert remoto.enviar_pendentes() is False and len(remoto.pendentes()) == 1 and banco.contar_pendentes() == 0
    # o agente reinicia com a rede ainda fora: o alerta continua lá
    outro = BancoRemoto(ClienteAgente("http://testserver", token, sessao=SessaoQueFalha()), pasta_fila=str(tmp / "fila"))
    assert len(outro.pendentes()) == 1
    estado["rede"] = True
    assert outro.enviar_pendentes() is True and banco.contar_pendentes() == 1 and outro.pendentes() == []


def test_alerta_recusado_pelo_painel_e_descartado_e_nao_trava_a_fila(painel):
    banco, _, http, token, _, _, tmp = painel
    camera = _registrar_camera(http, token)
    remoto = BancoRemoto(_cliente(http, token), pasta_fila=str(tmp / "fila"))
    remoto.registrar_alerta(99999, 1, "queda", 0.9, None)        # câmera que não é deste agente: 404, nunca vai funcionar
    remoto.registrar_alerta(camera["id"], 2, "queda", 0.9, None)  # este é válido e não pode ficar preso atrás do outro
    assert remoto.enviar_pendentes() is True and remoto.pendentes() == [] and banco.contar_pendentes() == 1


def test_sincronizador_envia_quadro_status_e_aplica_a_config_do_painel(painel):
    banco, _, http, token, _, _, _ = painel
    camera = _registrar_camera(http, token)
    banco.salvar_area_cama(camera["id"], [[[0.1, 0.5], [0.9, 0.5], [0.9, 0.9], [0.1, 0.9]]])
    banco.salvar_sensibilidade(0.2)

    class ServicoDeMentira:
        cfg_queda = ConfigQueda()
        ativa = True
        area_cama = []

        def jpeg_atual(self):
            return JPEG

        def status(self):
            return {"fps": 9.0, "pessoas": 1, "estado": "normal", "camera_online": True, "erro": None}

    servico = ServicoDeMentira()
    Sincronizador(_cliente(http, token), servico, camera["id"], aplicar_sensibilidade).sincronizar_uma_vez()
    assert http.get("/api/quadro").content == JPEG and http.get("/api/status").json()["fps"] == 9.0
    assert servico.area_cama == [[[0.1, 0.5], [0.9, 0.5], [0.9, 0.9], [0.1, 0.9]]]  # a cama marcada no painel chegou ao agente
    assert servico.ativa is True


# ------------------------------------------------------------------ do detector ao painel
def test_queda_simulada_no_agente_chega_ao_painel_com_foto_e_push(painel):
    banco, _, http, token, push, zap, tmp = painel
    camera = _registrar_camera(http, token)
    remoto = BancoRemoto(_cliente(http, token), pasta_fila=str(tmp / "fila"))
    servico = ServicoVisao(remoto, camera, "fake", cfg_queda=ConfigQueda(),
                           criar_captura=CapturaFalsa, criar_estimador=EstimadorFalso,
                           desenhar=lambda quadro, pessoas, fps: quadro,
                           notificador=NotificadorAlertas(pasta=str(tmp / "local"), cooldown_s=0))
    servico.iniciar()
    try:
        limite = time.time() + 10
        while time.time() < limite and not remoto.pendentes():
            time.sleep(0.1)
        assert remoto.pendentes(), "o detector não gerou alerta"
        assert remoto.enviar_pendentes() is True
    finally:
        servico.parar()
    alertas = http.get("/api/alertas").json()
    assert alertas and alertas[0]["tipo"] == "QUEDA" and alertas[0]["status"] == "PENDENTE"
    assert http.get(f"/api/alertas/{alertas[0]['id']}/imagem").content[:2] == b"\xff\xd8"  # a foto do detector chegou
    assert push.avisados and zap.avisados
