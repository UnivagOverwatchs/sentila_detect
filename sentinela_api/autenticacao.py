"""
autenticacao.py - Login do Sentinela: senha com hash, sessão em cookie e proteção contra tentativas em massa.

LÓGICA GERAL
------------
1. Senha: nunca guardada em texto. Usamos scrypt (biblioteca padrão do Python, sem dependência nova)
   com sal aleatório por usuário. O formato guardado é  scrypt$N$r$p$sal$hash.
2. Sessão: no login geramos um token aleatório de 256 bits e o entregamos num cookie HttpOnly
   (o JavaScript da página não consegue ler). No banco guardamos só o SHA-256 do token: quem
   ler o banco não consegue usar a sessão de ninguém.
3. Bloqueio: 5 erros seguidos para o mesmo usuário trancam o login por 15 minutos.
4. Papéis: ADMIN (tudo) e CUIDADOR (vê o painel, trata alertas, cadastra o próprio aparelho).

O login só é exigido quando LOGIN_OBRIGATORIO=1 (no servidor público). Em desenvolvimento local
continua aberto, como antes.
"""

import base64
import hashlib
import hmac
import secrets
import threading
import time
from typing import Dict, Optional, Tuple

COOKIE_SESSAO = "sentinela_sessao"
DURACAO_SESSAO_S = 7 * 24 * 3600
PAPEIS = ("ADMIN", "CUIDADOR")
TAMANHO_MIN_SENHA = 10

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode("ascii")


def _derivar(senha: str, sal: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=32, maxmem=64 * 1024 * 1024)


def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    derivado = _derivar(senha, sal, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(sal)}${_b64(derivado)}"


def verificar_senha(senha: str, guardado: str) -> bool:
    """Compara em tempo constante. Hash mal formado = senha errada (nunca derruba o login)."""
    try:
        formato, n, r, p, sal, esperado = guardado.split("$")
        if formato != "scrypt":
            return False
        derivado = _derivar(senha, base64.b64decode(sal), int(n), int(r), int(p))
        return hmac.compare_digest(derivado, base64.b64decode(esperado))
    except (ValueError, TypeError):
        return False


# Usado quando o usuário não existe: gasta o mesmo tempo de uma verificação real,
# para não revelar (pelo tempo de resposta) quais usuários existem.
HASH_FALSO = hash_senha("senha-que-ninguem-usa")


def validar_senha_nova(senha: str) -> Optional[str]:
    """Devolve a mensagem de erro, ou None se a senha serve."""
    if len(senha) < TAMANHO_MIN_SENHA:
        return f"A senha precisa ter pelo menos {TAMANHO_MIN_SENHA} caracteres."
    if senha.strip() != senha:
        return "A senha não pode começar nem terminar com espaço."
    if senha.lower() in {"1234567890", "senha12345", "password123", "0123456789", "qwertyuiop"}:
        return "Essa senha é muito comum."
    return None


def novo_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LimitadorLogin:
    """Tranca o login de um usuário depois de erros seguidos (em memória; reinicia com o servidor)."""

    def __init__(self, max_erros: int = 5, bloqueio_s: float = 15 * 60, agora=time.monotonic):
        self.max_erros = max_erros
        self.bloqueio_s = bloqueio_s
        self._agora = agora
        self._erros: Dict[str, Tuple[int, float]] = {}  # chave -> (erros, bloqueado_ate)
        self._lock = threading.Lock()

    def segundos_restantes(self, chave: str) -> int:
        with self._lock:
            _, ate = self._erros.get(chave, (0, 0.0))
            restante = ate - self._agora()
            return int(restante) + 1 if restante > 0 else 0

    def registrar_erro(self, chave: str) -> None:
        with self._lock:
            erros, ate = self._erros.get(chave, (0, 0.0))
            if ate and ate <= self._agora():  # bloqueio antigo acabou: recomeça a contar
                erros = 0
            erros += 1
            ate = self._agora() + self.bloqueio_s if erros >= self.max_erros else 0.0
            self._erros[chave] = (erros, ate)

    def registrar_sucesso(self, chave: str) -> None:
        with self._lock:
            self._erros.pop(chave, None)
