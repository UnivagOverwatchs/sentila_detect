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

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
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
CREATE TABLE IF NOT EXISTS assinatura_push (
    id         {pk},
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     VARCHAR(255) NOT NULL,
    auth       VARCHAR(255) NOT NULL,
    nome       VARCHAR(80),
    criada_em  TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS usuario (
    id          {pk},
    usuario     VARCHAR(60)  NOT NULL UNIQUE,
    nome        VARCHAR(120) NOT NULL,
    senha_hash  VARCHAR(255) NOT NULL,
    papel       VARCHAR(10)  NOT NULL DEFAULT 'CUIDADOR' CHECK (papel IN ('ADMIN', 'CUIDADOR')),
    ativo       BOOLEAN      NOT NULL DEFAULT {verdadeiro},
    criado_em   TIMESTAMP    NOT NULL
);
CREATE TABLE IF NOT EXISTS sessao (
    id          {pk},
    token_hash  VARCHAR(64) NOT NULL UNIQUE,
    usuario_id  INTEGER NOT NULL REFERENCES usuario(id),
    criada_em   TIMESTAMP NOT NULL,
    expira_em   TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS envio_push (
    id             {pk},
    assinatura_id  INTEGER,
    alerta_id      INTEGER,
    resultado      VARCHAR(10) NOT NULL,
    codigo         INTEGER,
    detalhe        VARCHAR(255),
    enviado_em     TIMESTAMP NOT NULL
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
        self._migrar()

    def _migrar(self) -> None:
        """Acrescenta colunas novas em tabelas que já existiam (o CREATE IF NOT EXISTS não altera tabela pronta)."""
        for comando in ("ALTER TABLE assinatura_push ADD COLUMN nome VARCHAR(80)",
                        "ALTER TABLE camera ADD COLUMN area_cama TEXT"):
            try:
                self._executar(comando)
            except Exception:  # noqa: BLE001 - a coluna já existe
                pass

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
        cameras = self._consultar("SELECT id, nome, local, ativa, area_cama FROM camera ORDER BY id")
        return [self._montar_camera(c) for c in cameras]

    @staticmethod
    def _montar_camera(c: Dict[str, Any]) -> Dict[str, Any]:
        c["ativa"] = bool(c["ativa"])
        try:
            c["area_cama"] = json.loads(c.get("area_cama") or "[]")
        except ValueError:
            c["area_cama"] = []
        return c

    def obter_camera(self, camera_id: int) -> Optional[Dict[str, Any]]:
        linhas = self._consultar("SELECT id, nome, local, ativa, area_cama FROM camera WHERE id = ?", (camera_id,))
        return self._montar_camera(linhas[0]) if linhas else None

    def salvar_area_cama(self, camera_id: int, poligonos: List[List[List[float]]]) -> Optional[Dict[str, Any]]:
        """Guarda as zonas de cama da câmera (polígonos com coordenadas de 0 a 1 da imagem). Lista vazia = sem cama."""
        self._executar("UPDATE camera SET area_cama = ? WHERE id = ?", (json.dumps(poligonos), camera_id))
        return self.obter_camera(camera_id)

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

    # ------------------------------------------------------------ Web Push
    def salvar_assinatura(self, endpoint: str, p256dh: str, auth: str, nome: Optional[str] = None) -> None:
        """Guarda (ou atualiza) a assinatura push de um aparelho. O nome só muda se vier preenchido."""
        self._executar(
            "INSERT INTO assinatura_push (endpoint, p256dh, auth, nome, criada_em) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth, "
            "nome = COALESCE(excluded.nome, assinatura_push.nome)",
            (endpoint, p256dh, auth, nome, _agora()))

    def remover_assinatura(self, endpoint: str) -> None:
        self._executar("DELETE FROM assinatura_push WHERE endpoint = ?", (endpoint,))

    def listar_assinaturas(self) -> List[Dict[str, Any]]:
        return self._consultar("SELECT id, endpoint, p256dh, auth FROM assinatura_push ORDER BY id")

    def listar_aparelhos(self) -> List[Dict[str, Any]]:
        """Aparelhos cadastrados para a tela de Configurações (sem expor endpoint nem chaves)."""
        return self._consultar(
            "SELECT s.id, s.nome, s.criada_em, "
            "(SELECT e.resultado FROM envio_push e WHERE e.assinatura_id = s.id ORDER BY e.id DESC LIMIT 1) AS ultimo_resultado, "
            "(SELECT e.enviado_em FROM envio_push e WHERE e.assinatura_id = s.id ORDER BY e.id DESC LIMIT 1) AS ultimo_envio "
            "FROM assinatura_push s ORDER BY s.id")

    def renomear_aparelho(self, aparelho_id: int, nome: str) -> bool:
        self._executar("UPDATE assinatura_push SET nome = ? WHERE id = ?", (nome, aparelho_id))
        return bool(self._consultar("SELECT id FROM assinatura_push WHERE id = ?", (aparelho_id,)))

    def remover_aparelho(self, aparelho_id: int) -> bool:
        existia = bool(self._consultar("SELECT id FROM assinatura_push WHERE id = ?", (aparelho_id,)))
        self._executar("DELETE FROM assinatura_push WHERE id = ?", (aparelho_id,))
        return existia

    def registrar_envio_push(self, assinatura_id: Optional[int], alerta_id: Optional[int], resultado: str,
                             codigo: Optional[int] = None, detalhe: Optional[str] = None) -> None:
        """Guarda o resultado de cada tentativa de push (OK ou FALHA) para auditoria."""
        self._executar(
            "INSERT INTO envio_push (assinatura_id, alerta_id, resultado, codigo, detalhe, enviado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (assinatura_id, alerta_id, resultado, codigo, (detalhe or "")[:255] or None, _agora()))

    def listar_envios_push(self, limite: int = 50) -> List[Dict[str, Any]]:
        return self._consultar("SELECT id, assinatura_id, alerta_id, resultado, codigo, detalhe, enviado_em "
                               "FROM envio_push ORDER BY id DESC LIMIT ?", (limite,))

    # ------------------------------------------------------------ usuários e sessões (login)
    _CAMPOS_USUARIO = "id, usuario, nome, papel, ativo, criado_em"

    @staticmethod
    def _usuario_publico(linha: Dict[str, Any]) -> Dict[str, Any]:
        linha["ativo"] = bool(linha["ativo"])
        return linha

    def contar_usuarios(self) -> int:
        return self._consultar("SELECT COUNT(*) AS n FROM usuario")[0]["n"]

    def criar_usuario(self, usuario: str, nome: str, senha_hash: str, papel: str = "CUIDADOR") -> Dict[str, Any]:
        novo_id = self._inserir("INSERT INTO usuario (usuario, nome, senha_hash, papel, criado_em) VALUES (?, ?, ?, ?, ?)",
                                (usuario, nome, senha_hash, papel, _agora()))
        return self.obter_usuario(novo_id)

    def obter_usuario(self, usuario_id: int) -> Optional[Dict[str, Any]]:
        linhas = self._consultar(f"SELECT {self._CAMPOS_USUARIO} FROM usuario WHERE id = ?", (usuario_id,))
        return self._usuario_publico(linhas[0]) if linhas else None

    def obter_usuario_para_login(self, usuario: str) -> Optional[Dict[str, Any]]:
        """Inclui o hash da senha: use só na verificação do login, nunca devolva à API."""
        linhas = self._consultar(f"SELECT {self._CAMPOS_USUARIO}, senha_hash FROM usuario WHERE usuario = ?", (usuario,))
        return self._usuario_publico(linhas[0]) if linhas else None

    def listar_usuarios(self) -> List[Dict[str, Any]]:
        return [self._usuario_publico(u)
                for u in self._consultar(f"SELECT {self._CAMPOS_USUARIO} FROM usuario ORDER BY id")]

    def atualizar_usuario(self, usuario_id: int, **campos) -> Optional[Dict[str, Any]]:
        permitidos = {k: v for k, v in campos.items() if k in {"nome", "papel", "ativo", "senha_hash"} and v is not None}
        if permitidos:
            sets = ", ".join(f"{k} = ?" for k in permitidos)  # nomes de coluna vêm de lista fechada
            self._executar(f"UPDATE usuario SET {sets} WHERE id = ?", (*permitidos.values(), usuario_id))
        return self.obter_usuario(usuario_id)

    def criar_sessao(self, token_hash: str, usuario_id: int, duracao_s: int) -> None:
        agora = _agora()
        self._executar("INSERT INTO sessao (token_hash, usuario_id, criada_em, expira_em) VALUES (?, ?, ?, ?)",
                       (token_hash, usuario_id, agora, agora + timedelta(seconds=duracao_s)))

    def obter_usuario_da_sessao(self, token_hash: str) -> Optional[Dict[str, Any]]:
        """Usuário ativo dono de uma sessão ainda válida; None se expirou, foi encerrada ou o usuário foi desativado."""
        linhas = self._consultar(
            "SELECT u.id, u.usuario, u.nome, u.papel, u.ativo, u.criado_em FROM sessao s "
            "JOIN usuario u ON u.id = s.usuario_id WHERE s.token_hash = ? AND s.expira_em > ?",
            (token_hash, _agora()))
        if not linhas or not linhas[0]["ativo"]:
            return None
        return self._usuario_publico(linhas[0])

    def encerrar_sessao(self, token_hash: str) -> None:
        self._executar("DELETE FROM sessao WHERE token_hash = ?", (token_hash,))

    def encerrar_sessoes_do_usuario(self, usuario_id: int) -> None:
        self._executar("DELETE FROM sessao WHERE usuario_id = ?", (usuario_id,))

    def limpar_sessoes_expiradas(self) -> None:
        self._executar("DELETE FROM sessao WHERE expira_em <= ?", (_agora(),))
