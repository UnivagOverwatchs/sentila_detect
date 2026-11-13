"""Vigia de câmeras: avisa (push e WhatsApp) quando uma câmera ativa fica sem sinal, uma vez, e quando volta."""

from sentinela_api.banco import Banco
from sentinela_api.vigia import VigiaCameras


class ServicoFalso:
    def __init__(self):
        self.vistos = {}

    def vistos_ha_s(self):
        return dict(self.vistos)


class Avisos:
    def __init__(self):
        self.push, self.zap = [], []

    def avisar_texto(self, *args):  # usado como push (titulo, corpo, tag) e como WhatsApp (texto)
        (self.push if len(args) == 3 else self.zap).append(args)


def _montar(tmp_path):
    banco = Banco(str(tmp_path / "v.db"), usar_postgres=False)
    servico, avisos = ServicoFalso(), Avisos()
    vigia = VigiaCameras(banco, servico, push=avisos, notificador_remoto=avisos, limite_s=300)
    return banco, servico, avisos, vigia


def test_camera_sem_sinal_avisa_uma_vez_e_avisa_quando_volta(tmp_path):
    banco, servico, avisos, vigia = _montar(tmp_path)
    cam = banco.garantir_camera("Quarto 1", "T", "agente:1:Quarto 1")
    servico.vistos[cam["id"]] = 10
    assert vigia.verificar() == {"caiu": [], "voltou": []}
    servico.vistos[cam["id"]] = 400  # 6 min sem notícias
    assert [c["id"] for c in vigia.verificar()["caiu"]] == [cam["id"]]
    assert vigia.verificar()["caiu"] == []  # não repete o aviso a cada rodada
    assert len(avisos.push) == 1 and len(avisos.zap) == 1 and "Quarto 1" in avisos.push[0][0]
    servico.vistos[cam["id"]] = 2
    assert [c["id"] for c in vigia.verificar()["voltou"]] == [cam["id"]]
    assert len(avisos.push) == 2 and "voltou" in avisos.push[1][0]


def test_camera_desligada_no_painel_ou_que_nunca_conectou_nao_avisa(tmp_path):
    banco, servico, avisos, vigia = _montar(tmp_path)
    desligada = banco.garantir_camera("Sala", "T", "agente:1:Sala")
    banco.atualizar_camera(desligada["id"], ativa=False)
    banco.garantir_camera("Antiga", "T", "0")  # computador antigo que grava direto no banco: nunca "fala"
    servico.vistos[desligada["id"]] = 9999
    assert vigia.verificar() == {"caiu": [], "voltou": []}
    assert avisos.push == [] and avisos.zap == []
