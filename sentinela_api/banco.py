"""
banco.py - Persistência em PostgreSQL seguindo o modelo lógico da documentação (Figura 9).

Conexão: variáveis POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER e POSTGRES_PASSWORD
(do .env). As tabelas NÃO são criadas ao abrir o banco: chame `criar_tabelas()` (ou rode
`python servidor.py --criar-tabelas`) quando quiser criá-las.

LGPD: nenhuma tabela guarda vídeo. Só a foto do momento do alerta (caminho do arquivo),
necessária para o cuidador confirmar a ocorrência.

Acesso concorrente: a thread de visão grava e as rotas da API leem ao mesmo tempo;
um pool de conexões do psycopg atende as duas.
"""

import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS camera (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(80)  NOT NULL,
    local       VARCHAR(60),
    url_stream  VARCHAR(255) NOT NULL,
    ativa       BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS evento (
    id           SERIAL PRIMARY KEY,
    camera_id    INTEGER NOT NULL REFERENCES camera(id),
    track_id     INTEGER NOT NULL,
    tipo         VARCHAR(20) NOT NULL CHECK (tipo IN ('QUEDA', 'MOVIMENTO_ANOMALO')),
    confianca    NUMERIC(4,3) NOT NULL,
    ocorrido_em  TIMESTAMP NOT NULL,
    imagem       VARCHAR(255)
);
CREATE TABLE IF NOT EXISTS alerta (
    id          SERIAL PRIMARY KEY,
    evento_id   INTEGER NOT NULL UNIQUE REFERENCES evento(id),
    status      VARCHAR(15) NOT NULL DEFAULT 'PENDENTE'
                CHECK (status IN ('PENDENTE', 'RESOLVIDO', 'FALSO_ALARME')),
    tratado_por VARCHAR(120),
    tratado_em  TIMESTAMP
);
CREATE TABLE IF NOT EXISTS contato_emergencia (
    id        SERIAL PRIMARY KEY,
    nome      VARCHAR(120) NOT NULL,
    telefone  VARCHAR(20)  NOT NULL,
    tipo      VARCHAR(30)
);
CREATE TABLE IF NOT EXISTS assinatura_push (
    id         SERIAL PRIMARY KEY,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     VARCHAR(255) NOT NULL,
    auth       VARCHAR(255) NOT NULL,
    criada_em  TIMESTAMP NOT NULL
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


def _serializavel(linha: Dict[str, Any]) -> Dict[str, Any]:
    """Datas viram texto ISO e NUMERIC vira float, para a API e o WebSocket gerarem JSON direto."""
    return {k: (v.isoformat(timespec="seconds") if isinstance(v, datetime)
                else float(v) if isinstance(v, Decimal) else v) for k, v in linha.items()}


def dsn_do_ambiente() -> str:
    """Monta a string de conexão a partir das variáveis POSTGRES_* (carregadas do .env)."""
    return (f"host={os.getenv('POSTGRES_HOST', 'localhost')} port={os.getenv('POSTGRES_PORT', '5432')} "
            f"dbname={os.getenv('POSTGRES_DB', 'sentinela')} user={os.getenv('POSTGRES_USER', 'sentinelas')} "
            f"password={os.getenv('POSTGRES_PASSWORD', '')}")


class Banco:
    """Repositório simples: cada método é uma operação de negócio."""

    def __init__(self, dsn: Optional[str] = None, schema: Optional[str] = None):
        """`schema` isola as tabelas num schema próprio (usado nos testes)."""
        self._schema = schema
        opcoes = f"-c search_path={schema}" if schema else None
        self._pool = ConnectionPool(dsn or dsn_do_ambiente(), min_size=1, max_size=5, open=True,
                                    kwargs={"row_factory": dict_row, "options": opcoes})

    def criar_tabelas(self) -> None:
        """Cria as tabelas (se não existirem) e a linha única de configuração. Só roda quando chamado."""
        with self._pool.connection() as con:
            if self._schema:
                con.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            con.execute(_ESQUEMA)
            con.execute("INSERT INTO configuracao (id, sensibilidade, atualizado_em) VALUES (1, 0.65, %s) "
                        "ON CONFLICT (id) DO NOTHING", (_agora(),))

    def fechar(self) -> None:
        self._pool.close()

    # ------------------------------------------------------------ utilitários
    def _consultar(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self._pool.connection() as con:
            return [_serializavel(linha) for linha in con.execute(sql, params).fetchall()]

    def _executar(self, sql: str, params: tuple = (), retornar_id: bool = False) -> Optional[int]:
        """Executa uma escrita. Com `retornar_id`, o SQL deve terminar em RETURNING id."""
        with self._pool.connection() as con:
            cursor = con.execute(sql, params)
            return cursor.fetchone()["id"] if retornar_id else None

    # ------------------------------------------------------------ câmeras
    def garantir_camera(self, nome: str, local: str, url_stream: str) -> Dict[str, Any]:
        """Cadastra a câmera da fonte de vídeo na primeira execução e devolve o registro."""
        existente = self._consultar("SELECT * FROM camera WHERE url_stream = %s", (url_stream,))
        if existente:
            return existente[0]
        novo_id = self._executar("INSERT INTO camera (nome, local, url_stream) VALUES (%s, %s, %s) RETURNING id",
                                 (nome, local, url_stream), retornar_id=True)
        return self.obter_camera(novo_id)

    def listar_cameras(self) -> List[Dict[str, Any]]:
        cameras = self._consultar("SELECT id, nome, local, ativa FROM camera ORDER BY id")
        for c in cameras:
            c["ativa"] = bool(c["ativa"])
        return cameras

    def obter_camera(self, camera_id: int) -> Optional[Dict[str, Any]]:
        linhas = self._consultar("SELECT id, nome, local, ativa FROM camera WHERE id = %s", (camera_id,))
        if not linhas:
            return None
        linhas[0]["ativa"] = bool(linhas[0]["ativa"])
        return linhas[0]

    def atualizar_camera(self, camera_id: int, **campos) -> Optional[Dict[str, Any]]:
        permitidos = {k: v for k, v in campos.items() if k in {"nome", "local", "ativa"} and v is not None}
        if permitidos:
            # Nomes de coluna vêm de uma lista fechada (sem risco de SQL injection); valores vão como parâmetros.
            sets = ", ".join(f"{k} = %s" for k in permitidos)
            self._executar(f"UPDATE camera SET {sets} WHERE id = %s", (*permitidos.values(), camera_id))
        return self.obter_camera(camera_id)

    # ------------------------------------------------------------ eventos e alertas
    def registrar_alerta(self, camera_id: int, track_id: int, tipo_logica: str,
                         confianca: float, imagem: Optional[str]) -> Dict[str, Any]:
        """Cria o evento e o alerta PENDENTE correspondente (relação 1:1, como na documentação)."""
        evento_id = self._executar(
            "INSERT INTO evento (camera_id, track_id, tipo, confianca, ocorrido_em, imagem) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (camera_id, track_id, TIPO_EVENTO[tipo_logica], round(confianca, 3), _agora(), imagem), retornar_id=True)
        alerta_id = self._executar("INSERT INTO alerta (evento_id) VALUES (%s) RETURNING id", (evento_id,),
                                    retornar_id=True)
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
        linhas = self._consultar(self._SELECT_ALERTA + " WHERE a.id = %s", (alerta_id,))
        return linhas[0] if linhas else None

    def listar_alertas(self, status: Optional[str] = None, tipo: Optional[str] = None,
                       limite: int = 100, depois_de_id: int = 0) -> List[Dict[str, Any]]:
        filtros, params = ["a.id > %s"], [depois_de_id]
        if status:
            filtros.append("a.status = %s")
            params.append(status)
        if tipo:
            filtros.append("e.tipo = %s")
            params.append(tipo)
        sql = self._SELECT_ALERTA + " WHERE " + " AND ".join(filtros) + " ORDER BY a.id DESC LIMIT %s"
        params.append(limite)
        return self._consultar(sql, tuple(params))

    def tratar_alerta(self, alerta_id: int, status: str, tratado_por: str) -> Optional[Dict[str, Any]]:
        """Fecha o alerta (Resolvido/Falso alarme) registrando quem tratou e quando (RF13)."""
        if status not in STATUS_VALIDOS - {"PENDENTE"}:
            raise ValueError(f"status inválido: {status}")
        self._executar("UPDATE alerta SET status = %s, tratado_por = %s, tratado_em = %s WHERE id = %s",
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
        novo_id = self._executar("INSERT INTO contato_emergencia (nome, telefone, tipo) VALUES (%s, %s, %s) RETURNING id",
                                 (nome, telefone, tipo), retornar_id=True)
        return self._consultar("SELECT * FROM contato_emergencia WHERE id = %s", (novo_id,))[0]

    def remover_contato(self, contato_id: int) -> None:
        self._executar("DELETE FROM contato_emergencia WHERE id = %s", (contato_id,))

    # ------------------------------------------------------------ configuração
    def obter_sensibilidade(self) -> float:
        return float(self._consultar("SELECT sensibilidade FROM configuracao WHERE id = 1")[0]["sensibilidade"])

    def salvar_sensibilidade(self, valor: float) -> None:
        self._executar("UPDATE configuracao SET sensibilidade = %s, atualizado_em = %s WHERE id = 1",
                       (round(valor, 2), _agora()))

    # ------------------------------------------------------------ Web Push
    def salvar_assinatura(self, endpoint: str, p256dh: str, auth: str) -> None:
        """Guarda (ou atualiza) a assinatura push de um aparelho."""
        self._executar(
            "INSERT INTO assinatura_push (endpoint, p256dh, auth, criada_em) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (endpoint) DO UPDATE SET p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth",
            (endpoint, p256dh, auth, _agora()))

    def remover_assinatura(self, endpoint: str) -> None:
        self._executar("DELETE FROM assinatura_push WHERE endpoint = %s", (endpoint,))

    def listar_assinaturas(self) -> List[Dict[str, Any]]:
        return self._consultar("SELECT endpoint, p256dh, auth FROM assinatura_push ORDER BY id")
