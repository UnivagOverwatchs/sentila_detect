"""Rotina diária: retenção LGPD apaga alertas tratados antigos e as fotos deles, nunca pendentes nem arquivos fora da pasta."""
from datetime import datetime, timedelta

from sentinela_api import manutencao
from sentinela_api.banco import Banco


def _envelhecer(banco, alerta_id, dias):
    quando = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    banco._executar("UPDATE evento SET ocorrido_em = ? WHERE id = (SELECT evento_id FROM alerta WHERE id = ?)", (quando, alerta_id))


def test_retencao_apaga_fotos_dos_alertas_tratados_antigos(tmp_path):
    banco = Banco(str(tmp_path / "m.db"), usar_postgres=False)
    pasta = tmp_path / "fotos"
    pasta.mkdir()
    velha, pendente = pasta / "velha.jpg", pasta / "pendente.jpg"
    velha.write_bytes(b"x")
    pendente.write_bytes(b"x")
    fora = tmp_path / "importante.txt"  # arquivo FORA da pasta de fotos: nunca pode ser apagado
    fora.write_text("não apagar")
    cam = banco.garantir_camera("Q", "T", "f")
    a1 = banco.registrar_alerta(cam["id"], 1, "queda", 0.9, str(velha))
    a2 = banco.registrar_alerta(cam["id"], 2, "queda", 0.9, str(pendente))
    a3 = banco.registrar_alerta(cam["id"], 3, "queda", 0.9, str(fora))
    banco.tratar_alerta(a1["id"], "RESOLVIDO", "x")
    banco.tratar_alerta(a3["id"], "RESOLVIDO", "x")
    for a in (a1, a2, a3):
        _envelhecer(banco, a["id"], 200)

    feito = manutencao.executar(banco, str(pasta), dias=90)

    assert feito == {"alertas": 2, "fotos": 1}
    assert not velha.exists() and pendente.exists() and fora.exists()
    assert [a["id"] for a in banco.listar_alertas()] == [a2["id"]]


def test_retencao_zero_guarda_tudo(tmp_path):
    banco = Banco(str(tmp_path / "m.db"), usar_postgres=False)
    cam = banco.garantir_camera("Q", "T", "f")
    a = banco.registrar_alerta(cam["id"], 1, "queda", 0.9, None)
    banco.tratar_alerta(a["id"], "RESOLVIDO", "x")
    _envelhecer(banco, a["id"], 999)
    assert manutencao.executar(banco, str(tmp_path), dias=0) == {"alertas": 0, "fotos": 0}
    assert len(banco.listar_alertas()) == 1
