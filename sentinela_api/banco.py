"""
banco.py - Persistência em SQLite seguindo o modelo lógico da documentação (Figura 9).

Por que SQLite nesta etapa?
  - Zero instalação (vem com o Python) e um único arquivo (sentinela.db).
  - As tabelas/colunas têm os mesmos nomes do modelo PostgreSQL da documentação,
    então a migração para a API Node.js + PostgreSQL é direta.

LGPD: nenhuma tabela guarda vídeo. Só a foto do momento do alerta (caminho do arquivo),
necessária para o cuidador confirmar a ocorrência.

Acesso concorrente: a thread de visão grava e as rotas da API leem ao mesmo tempo.
Usamos uma única conexão com `check_same_thread=False` protegida por um Lock.
"""

import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS camera (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        VARCHAR(80)  NOT NULL,
    local       VARCHAR(60),
    url_stream  VARCHAR(255) NOT NULL,
    ativa       BOOLEAN      NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS evento (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id    INTEGER NOT NULL REFERENCES camera(id),
    track_id     INTEGER NOT NULL,
    tipo         VARCHAR(20) NOT NULL CHECK (tipo IN ('QUEDA', 'MOVIMENTO_ANOMALO')),
    confianca    NUMERIC(4,3) NOT NULL,
    ocorrido_em  TIMESTAMP NOT NULL,
    imagem       VARCHAR(255)
);
CREATE TABLE IF NOT EXISTS alerta (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id   INTEGER NOT NULL UNIQUE REFERENCES evento(id),
    status      VARCHAR(15) NOT NULL DEFAULT 'PENDENTE'
                CHECK (status IN ('PENDENTE', 'RESOLVIDO', 'FALSO_ALARME')),
    tratado_por VARCHAR(120),
    tratado_em  TIMESTAMP
);
CREATE TABLE IF NOT EXISTS contato_emergencia (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      VARCHAR(120) NOT NULL,
    telefone  VARCHAR(20)  NOT NULL,
    tipo      VARCHAR(30)
);
CREATE TABLE IF NOT EXISTS configuracao (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    sensibilidade  NUMERIC(3,2) NOT NULL DEFAULT 0.65,
    atualizado_em  TIMESTAMP
);
"""

# Mapeia o tipo da lógica de queda para o enum TipoEvento da documentação.
TIPO_EVENTO = {"queda": "QUEDA", "pessoa_no_chao": "MOVIMENTO_ANOMALO"}
STATUS_VALIDOS = {"PENDENTE", "RESOLVIDO", "FALSO_ALARME"}


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Banco:
    """Repositório simples: cada método é uma operação de negócio."""

    def __init__(self, caminho: str = "sentinela.db"):
        self._con = sqlite3.connect(caminho, check_same_thread=False)
        self._con.row_factory = sqlite3.Row  # linhas viram objetos acessíveis por nome
        self._lock = threading.Lock()
        with self._lock:
            self._con.executescript(_ESQUEMA)
            self._con.execute(
                "INSERT OR IGNORE INTO configuracao (id, sensibilidade, atualizado_em) VALUES (1, 0.65, ?)",
                (_agora(),))
            self._con.commit()

    # ------------------------------------------------------------ utilitários
    def _consultar(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(linha) for linha in self._con.execute(sql, params).fetchall()]

    def _executar(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            cursor = self._con.execute(sql, params)
            self._con.commit()
            return cursor.lastrowid

    # ------------------------------------------------------------ câmeras
    def garantir_camera(self, nome: str, local: str, url_stream: str) -> Dict[str, Any]:
        """Cadastra a câmera da fonte de vídeo na primeira execução e devolve o registro."""
        existente = self._consultar("SELECT * FROM camera WHERE url_stream = ?", (url_stream,))
        if existente:
            return existente[0]
        novo_id = self._executar("INSERT INTO camera (nome, local, url_stream) VALUES (?, ?, ?)",
                                 (nome, local, url_stream))
        return self.obter_camera(novo_id)

    def listar_cameras(self) -> List[Dict[str, Any]]:
        cameras = self._consultar("SELECT id, nome, local, ativa FROM camera ORDER BY id")
        for c in cameras:
            c["ativa"] = bool(c["ativa"])
        return cameras

    def obter_camera(self, camera_id: int) -> Optional[Dict[str, Any]]:
        linhas = self._consultar("SELECT id, nome, local, ativa FROM camera WHERE id = ?", (camera_id,))
        if not linhas:
            return None
        linhas[0]["ativa"] = bool(linhas[0]["ativa"])
        return linhas[0]

    def atualizar_camera(self, camera_id: int, **campos) -> Optional[Dict[str, Any]]:
        permitidos = {k: v for k, v in campos.items() if k in {"nome", "local", "ativa"} and v is not None}
        if permitidos:
            # Nomes de coluna vêm de uma lista fechada (sem risco de SQL injection); valores vão como parâmetros.
            sets = ", ".join(f"{k} = ?" for k in permitidos)
            self._executar(f"UPDATE camera SET {sets} WHERE id = ?", (*permitidos.values(), camera_id))
        return self.obter_camera(camera_id)

    # ------------------------------------------------------------ eventos e alertas
    def registrar_alerta(self, camera_id: int, track_id: int, tipo_logica: str,
                         confianca: float, imagem: Optional[str]) -> Dict[str, Any]:
        """Cria o evento e o alerta PENDENTE correspondente (relação 1:1, como na documentação)."""
        evento_id = self._executar(
            "INSERT INTO evento (camera_id, track_id, tipo, confianca, ocorrido_em, imagem) VALUES (?, ?, ?, ?, ?, ?)",
            (camera_id, track_id, TIPO_EVENTO[tipo_logica], round(confianca, 3), _agora(), imagem))
        alerta_id = self._executar("INSERT INTO alerta (evento_id) VALUES (?)", (evento_id,))
        return self.obter_alerta(alerta_id)

    _SELECT_ALERTA = """
        SELECT a.id, a.status, a.tratado_por, a.tratado_em,
               e.tipo, e.confianca, e.ocorrido_em, e.track_id, e.imagem,
               c.id AS camera_id, c.nome AS camera_nome, c.local AS camera_local
          FROM alerta a
          JOIN evento e ON e.id = a.evento_id
          JOIN camera c ON c.id = e.camera_id
    """

    def obter_alerta(self, alerta_id: int) -> Optional[Dict[str, Any]]:
        linhas = self._consultar(self._SELECT_ALERTA + " WHERE a.id = ?", (alerta_id,))
        return linhas[0] if linhas else None

    def listar_alertas(self, status: Optional[str] = None, tipo: Optional[str] = None,
                       limite: int = 100, depois_de_id: int = 0) -> List[Dict[str, Any]]:
        filtros, params = ["a.id > ?"], [depois_de_id]
        if status:
            filtros.append("a.status = ?")
            params.append(status)
        if tipo:
            filtros.append("e.tipo = ?")
            params.append(tipo)
        sql = self._SELECT_ALERTA + " WHERE " + " AND ".join(filtros) + " ORDER BY a.id DESC LIMIT ?"
        params.append(limite)
        return self._consultar(sql, tuple(params))

    def tratar_alerta(self, alerta_id: int, status: str, tratado_por: str) -> Optional[Dict[str, Any]]:
        """Fecha o alerta (Resolvido/Falso alarme) registrando quem tratou e quando (RF13)."""
        if status not in STATUS_VALIDOS - {"PENDENTE"}:
            raise ValueError(f"status inválido: {status}")
        self._executar("UPDATE alerta SET status = ?, tratado_por = ?, tratado_em = ? WHERE id = ?",
                       (status, tratado_por, _agora(), alerta_id))
        return self.obter_alerta(alerta_id)

    def contar_pendentes(self) -> int:
        return self._consultar("SELECT COUNT(*) AS n FROM alerta WHERE status = 'PENDENTE'")[0]["n"]

    def ultimo_alerta_id(self) -> int:
        return self._consultar("SELECT COALESCE(MAX(id), 0) AS n FROM alerta")[0]["n"]

    # ------------------------------------------------------------ contatos de emergência
    def listar_contatos(self) -> List[Dict[str, Any]]:
        return self._consultar("SELECT * FROM contato_emergencia ORDER BY id")

    def criar_contato(self, nome: str, telefone: str, tipo: str) -> Dict[str, Any]:
        novo_id = self._executar("INSERT INTO contato_emergencia (nome, telefone, tipo) VALUES (?, ?, ?)",
                                 (nome, telefone, tipo))
        return self._consultar("SELECT * FROM contato_emergencia WHERE id = ?", (novo_id,))[0]

    def remover_contato(self, contato_id: int) -> None:
        self._executar("DELETE FROM contato_emergencia WHERE id = ?", (contato_id,))

    # ------------------------------------------------------------ configuração
    def obter_sensibilidade(self) -> float:
        return float(self._consultar("SELECT sensibilidade FROM configuracao WHERE id = 1")[0]["sensibilidade"])

    def salvar_sensibilidade(self, valor: float) -> None:
        self._executar("UPDATE configuracao SET sensibilidade = ?, atualizado_em = ? WHERE id = 1",
                       (round(valor, 2), _agora()))
