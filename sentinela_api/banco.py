"""
banco.py - Persistência seguindo o modelo lógico da documentação (Figura 9).

DOIS BANCOS, O MESMO CÓDIGO
---------------------------
  - PostgreSQL (servidor da equipe): usado quando o .env tem DATABASE_URL ou PGHOST.
  - SQLite (arquivo local sentinela.db): usado quando não há Postgres configurado,
    útil para desenvolver e testar sem rede.

As consultas são escritas uma vez, com "?" como marcador de parâmetro. A classe
_Dialeto troca "?" por "%s" no Postgres e cuida das poucas diferenças de esquema
(SERIAL x AUTOINCREMENT, TRUE x 1). Todo INSERT usa "RETURNING id", que os dois suportam.

Segurança: valores SEMPRE vão como parâmetros (nunca concatenados no SQL) -> sem SQL injection.
A senha do banco fica só no .env (fora do git) e nunca é impressa.

LGPD: nenhuma tabela guarda vídeo. Só o caminho da foto do momento do alerta.

Concorrência: a thread de visão grava e a API lê ao mesmo tempo. Uma única conexão
protegida por Lock basta para o volume de uma ILPI; se a conexão com o servidor cair,
reconectamos uma vez e repetimos a operação.
"""

import os
import sqlite3
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

# ----------------------------------------------------------------- esquemas
_ESQUEMA_COMUM = """
CREATE TABLE IF NOT EXISTS camera (
    id          {pk},
    nome        VARCHAR(80)  NOT NULL,
    local       VARCHAR(60),
    url_stream  VARCHAR(255) NOT NULL,
    ativa       BOOLEAN      NOT NULL DEFAULT {verdadeiro}
);
CREATE TABLE IF NOT EXISTS evento (
    id           {pk},
    camera_id    INTEGER NOT NULL REFERENCES camera(id),
    track_id     INTEGER NOT NULL,
    tipo         VARCHAR(20) NOT NULL CHECK (tipo IN ('QUEDA', 'MOVIMENTO_ANOMALO')),
    confianca    NUMERIC(4,3) NOT NULL,
    ocorrido_em  TIMESTAMP NOT NULL,
    imagem       VARCHAR(255)
);
CREATE TABLE IF NOT EXISTS alerta (
    id          {pk},
    evento_id   INTEGER NOT NULL UNIQUE REFERENCES evento(id),
    status      VARCHAR(15) NOT NULL DEFAULT 'PENDENTE'
                CHECK (status IN ('PENDENTE', 'RESOLVIDO', 'FALSO_ALARME')),
    tratado_por VARCHAR(120),
    tratado_em  TIMESTAMP
);
CREATE TABLE IF NOT EXISTS contato_emergencia (
    id        {pk},
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


def _agora() -> datetime:
    return datetime.now().replace(microsecond=0)


def _para_json(valor: Any) -> Any:
    """Postgres devolve datetime/Decimal; a API e o WebSocket precisam de tipos JSON."""
    if isinstance(valor, datetime):
        return valor.isoformat(timespec="seconds")
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def postgres_configurado() -> bool:
    return bool(os.getenv("DATABASE_URL") or os.getenv("PGHOST"))


# ----------------------------------------------------------------- dialetos
class _Dialeto:
    """Esconde as diferenças entre SQLite e PostgreSQL do resto da classe Banco."""

    nome = "base"
    erros_conexao: tuple = ()

    def conectar(self):
        raise NotImplementedError

    def sql(self, texto: str) -> str:
        return texto

    def params(self, params: tuple) -> tuple:
        return params

    def esquema(self) -> str:
        raise NotImplementedError

    def descricao(self) -> str:
        return self.nome


class _SQLite(_Dialeto):
    nome = "SQLite"

    def __init__(self, caminho: str):
        self.caminho = caminho

    def conectar(self):
        con = sqlite3.connect(self.caminho, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def params(self, params: tuple) -> tuple:
        # sqlite3 não converte datetime automaticamente nas versões novas do Python.
        return tuple(p.isoformat(timespec="seconds") if isinstance(p, datetime) else p for p in params)

    def esquema(self) -> str:
        return _ESQUEMA_COMUM.format(pk="INTEGER PRIMARY KEY AUTOINCREMENT", verdadeiro="1")

    def descricao(self) -> str:
        return f"SQLite ({self.caminho})"


class _Postgres(_Dialeto):
    nome = "PostgreSQL"

    def __init__(self):
        import psycopg  # import só aqui: quem usa SQLite não precisa ter o psycopg
        self._psycopg = psycopg
        self.erros_conexao = (psycopg.OperationalError, psycopg.InterfaceError)
        # DATABASE_URL tem prioridade; sem ela, o psycopg lê sozinho PGHOST, PGPORT,
        # PGDATABASE, PGUSER, PGPASSWORD e PGSSLMODE do ambiente.
        self.conninfo = os.getenv("DATABASE_URL", "")

    def conectar(self):
        from psycopg.rows import dict_row
        return self._psycopg.connect(self.conninfo, autocommit=True, row_factory=dict_row, connect_timeout=10)

    def sql(self, texto: str) -> str:
        return texto.replace("?", "%s")

    def esquema(self) -> str:
        return _ESQUEMA_COMUM.format(pk="SERIAL PRIMARY KEY", verdadeiro="TRUE")

    def descricao(self) -> str:
        # Mostra servidor e banco, nunca usuário/senha.
        info = self._psycopg.conninfo.conninfo_to_dict(self.conninfo) if self.conninfo else {}
        host = info.get("host") or os.getenv("PGHOST", "?")
        banco = info.get("dbname") or os.getenv("PGDATABASE", "?")
        return f"PostgreSQL ({host}/{banco})"


# ----------------------------------------------------------------- repositório
class Banco:
    """Repositório: cada método é uma operação de negócio."""

    def __init__(self, caminho_sqlite: str = "sentinela.db", usar_postgres: Optional[bool] = None):
        if usar_postgres is None:
            usar_postgres = postgres_configurado()
        self._dialeto: _Dialeto = _Postgres() if usar_postgres else _SQLite(caminho_sqlite)
        self._lock = threading.Lock()
        self._con = self._dialeto.conectar()
        # Cria as tabelas que ainda não existem (não mexe em tabelas/dados existentes).
        for comando in filter(str.strip, self._dialeto.esquema().split(";")):
            self._executar(comando)
        self._executar("INSERT INTO configuracao (id, sensibilidade, atualizado_em) VALUES (1, 0.65, ?) "
                       "ON CONFLICT (id) DO NOTHING", (_agora(),))

    @property
    def descricao(self) -> str:
        return self._dialeto.descricao()

    # ------------------------------------------------------------ utilitários
    def _rodar(self, sql: str, params: tuple, buscar: str):
        """Executa com lock; se a conexão com o servidor caiu, reconecta uma vez e repete."""
        sql, params = self._dialeto.sql(sql), self._dialeto.params(params)
        with self._lock:
            for tentativa in (1, 2):
                try:
                    cursor = self._con.execute(sql, params)
                    resultado = cursor.fetchall() if buscar == "todos" else cursor.fetchone() if buscar == "um" else None
                    self._con.commit()
                    return resultado
                except self._dialeto.erros_conexao:
                    if tentativa == 2:
                        raise
                    self._con = self._dialeto.conectar()

    def _consultar(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        return [{k: _para_json(v) for k, v in dict(linha).items()} for linha in self._rodar(sql, params, "todos")]

    def _inserir(self, sql: str, params: tuple) -> int:
        """INSERT ... RETURNING id (funciona no SQLite >= 3.35 e no Postgres)."""
        linha = self._rodar(sql + " RETURNING id", params, "um")
        return dict(linha)["id"]

    def _executar(self, sql: str, params: tuple = ()) -> None:
        self._rodar(sql, params, "nada")

    # ------------------------------------------------------------ câmeras
    def garantir_camera(self, nome: str, local: str, url_stream: str) -> Dict[str, Any]:
        """Cadastra a câmera da fonte de vídeo na primeira execução e devolve o registro."""
        existente = self._consultar("SELECT id FROM camera WHERE url_stream = ?", (url_stream,))
        if existente:
            return self.obter_camera(existente[0]["id"])
        novo_id = self._inserir("INSERT INTO camera (nome, local, url_stream) VALUES (?, ?, ?)",
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
            # Nomes de coluna vêm de uma lista fechada; valores vão como parâmetros.
            sets = ", ".join(f"{k} = ?" for k in permitidos)
            self._executar(f"UPDATE camera SET {sets} WHERE id = ?", (*permitidos.values(), camera_id))
        return self.obter_camera(camera_id)

    # ------------------------------------------------------------ eventos e alertas
    def registrar_alerta(self, camera_id: int, track_id: int, tipo_logica: str,
                         confianca: float, imagem: Optional[str]) -> Dict[str, Any]:
        """Cria o evento e o alerta PENDENTE correspondente (relação 1:1, como na documentação)."""
        evento_id = self._inserir(
            "INSERT INTO evento (camera_id, track_id, tipo, confianca, ocorrido_em, imagem) VALUES (?, ?, ?, ?, ?, ?)",
            (camera_id, track_id, TIPO_EVENTO[tipo_logica], round(confianca, 3), _agora(), imagem))
        alerta_id = self._inserir("INSERT INTO alerta (evento_id) VALUES (?)", (evento_id,))
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
        return self._consultar("SELECT id, nome, telefone, tipo FROM contato_emergencia ORDER BY id")

    def criar_contato(self, nome: str, telefone: str, tipo: str) -> Dict[str, Any]:
        novo_id = self._inserir("INSERT INTO contato_emergencia (nome, telefone, tipo) VALUES (?, ?, ?)",
                                (nome, telefone, tipo))
        return self._consultar("SELECT id, nome, telefone, tipo FROM contato_emergencia WHERE id = ?", (novo_id,))[0]

    def remover_contato(self, contato_id: int) -> None:
        self._executar("DELETE FROM contato_emergencia WHERE id = ?", (contato_id,))

    # ------------------------------------------------------------ configuração
    def obter_sensibilidade(self) -> float:
        return float(self._consultar("SELECT sensibilidade FROM configuracao WHERE id = 1")[0]["sensibilidade"])

    def salvar_sensibilidade(self, valor: float) -> None:
        self._executar("UPDATE configuracao SET sensibilidade = ?, atualizado_em = ? WHERE id = 1",
                       (round(valor, 2), _agora()))
