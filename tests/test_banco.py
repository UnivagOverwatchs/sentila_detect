"""
Testes do banco: retenção (LGPD), exclusão em transação, índices e o conjunto de conexões do Postgres.

O teste de Postgres só roda com TEST_DATABASE_URL definido (ex.: um Postgres de teste no Docker):
    docker run --rm -d -p 55432:5432 -e POSTGRES_PASSWORD=teste -e POSTGRES_DB=teste postgres:16-alpine
    set TEST_DATABASE_URL=postgresql://postgres:teste@127.0.0.1:55432/teste
"""

import os
import threading
import time
from datetime import datetime, timedelta

import pytest

from sentinela_api.banco import Banco


@pytest.fixture
def banco(tmp_path):
    return Banco(str(tmp_path / "t.db"), usar_postgres=False)


def _envelhecer(banco, alerta_id, dias):
    quando = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    banco._executar("UPDATE evento SET ocorrido_em = ? WHERE id = (SELECT evento_id FROM alerta WHERE id = ?)",
                    (quando, alerta_id))


def test_retencao_apaga_so_tratados_antigos_e_devolve_as_fotos(banco):
    cam = banco.garantir_camera("Q", "T", "f")
    velho_tratado = banco.registrar_alerta(cam["id"], 1, "queda", 0.9, "fotos/velho.jpg")
    velho_pendente = banco.registrar_alerta(cam["id"], 2, "queda", 0.9, "fotos/pendente.jpg")
    novo_tratado = banco.registrar_alerta(cam["id"], 3, "queda", 0.9, "fotos/novo.jpg")
    for a in (velho_tratado, novo_tratado):
        banco.tratar_alerta(a["id"], "RESOLVIDO", "x")
    _envelhecer(banco, velho_tratado["id"], 120)
    _envelhecer(banco, velho_pendente["id"], 120)

    fotos = banco.apagar_historico_antigo(dias=90)

    assert fotos == ["fotos/velho.jpg"]
    restantes = {a["id"] for a in banco.listar_alertas()}
    assert restantes == {velho_pendente["id"], novo_tratado["id"]}  # pendente NUNCA é apagado


def test_exclusao_de_camera_e_tudo_ou_nada(banco, monkeypatch):
    cam = banco.garantir_camera("Q", "T", "f")
    banco.registrar_alerta(cam["id"], 1, "queda", 0.9, None)
    original = banco._dialeto.params

    def falha_no_ultimo(params):  # simula o banco caindo no meio da exclusão (no DELETE da câmera)
        if params == (cam["id"],) and falha_no_ultimo.chamadas == 2:
            raise RuntimeError("queda no meio")
        falha_no_ultimo.chamadas += params == (cam["id"],)
        return original(params)
    falha_no_ultimo.chamadas = 0
    monkeypatch.setattr(banco._dialeto, "params", falha_no_ultimo)
    with pytest.raises(RuntimeError):
        banco.excluir_camera(cam["id"])
    monkeypatch.setattr(banco._dialeto, "params", original)
    assert banco.obter_camera(cam["id"]) is not None
    assert len(banco.listar_alertas()) == 1  # nada foi apagado pela metade


def test_indices_existem(banco):
    nomes = {l["name"] for l in banco._consultar("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_alerta_pendente", "idx_evento_camera", "idx_evento_ocorrido", "idx_sessao_expira"} <= nomes


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="defina TEST_DATABASE_URL para testar no Postgres")
def test_postgres_pool_consulta_lenta_nao_trava_as_outras(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    banco = Banco(usar_postgres=True)
    try:
        assert banco.usa_pool
        cam = banco.garantir_camera("Pool", "T", f"pool-{time.time()}")
        lenta = threading.Thread(target=lambda: banco._consultar("SELECT pg_sleep(2)"))
        lenta.start()
        time.sleep(0.2)
        inicio = time.monotonic()
        banco.registrar_alerta(cam["id"], 1, "queda", 0.9, None)  # antes ficava 2 s esperando a consulta lenta
        assert time.monotonic() - inicio < 1.0
        lenta.join()
        assert banco.excluir_camera(cam["id"]) == []
    finally:
        banco.fechar()
