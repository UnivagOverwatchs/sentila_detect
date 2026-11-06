"""
usuarios.py - Gerencia usuários do login pela linha de comando (a senha é pedida no terminal, nunca como argumento).

Uso (na pasta do projeto, com o .env configurado):
    python -m sentinela_api.usuarios criar --usuario ana --nome "Ana Souza" --papel ADMIN
    python -m sentinela_api.usuarios listar
    python -m sentinela_api.usuarios senha --usuario ana
    python -m sentinela_api.usuarios desativar --usuario ana
    python -m sentinela_api.usuarios ativar --usuario ana

O primeiro usuário ADMIN precisa nascer por aqui; depois os demais podem ser criados pela tela.
"""

import argparse
import getpass
import re
import sys

from dotenv import load_dotenv

from . import autenticacao as auth
from .banco import Banco

_LOGIN = re.compile(r"^[a-z0-9._-]{3,60}$")


def _pedir_senha() -> str:
    while True:
        senha = getpass.getpass("Senha: ")
        erro = auth.validar_senha_nova(senha)
        if erro:
            print(erro)
            continue
        if getpass.getpass("Repita a senha: ") != senha:
            print("As senhas não conferem.")
            continue
        return senha


def main(argv=None, banco: Banco | None = None) -> int:
    parser = argparse.ArgumentParser(description="Usuários do Sentinela")
    sub = parser.add_subparsers(dest="comando", required=True)
    criar = sub.add_parser("criar")
    criar.add_argument("--usuario", required=True)
    criar.add_argument("--nome")
    criar.add_argument("--papel", choices=auth.PAPEIS, default="CUIDADOR")
    sub.add_parser("listar")
    for nome in ("senha", "ativar", "desativar"):
        sub.add_parser(nome).add_argument("--usuario", required=True)
    args = parser.parse_args(argv)

    if banco is None:
        load_dotenv()
        banco = Banco()
    if args.comando == "listar":
        for u in banco.listar_usuarios():
            print(f"{u['id']:>3}  {u['usuario']:<20} {u['papel']:<9} {'ativo' if u['ativo'] else 'DESATIVADO'}  {u['nome']}")
        return 0

    login = args.usuario.strip().lower()
    if args.comando == "criar":
        if not _LOGIN.match(login):
            print("Login inválido: use 3 a 60 letras minúsculas, números, ponto, hífen ou sublinhado.")
            return 1
        if banco.obter_usuario_para_login(login):
            print("Já existe um usuário com esse login.")
            return 1
        banco.criar_usuario(login, (args.nome or login).strip(), auth.hash_senha(_pedir_senha()), args.papel)
        print(f"Usuário '{login}' criado como {args.papel}.")
        return 0

    existente = banco.obter_usuario_para_login(login)
    if not existente:
        print("Usuário não encontrado.")
        return 1
    if args.comando == "senha":
        banco.atualizar_usuario(existente["id"], senha_hash=auth.hash_senha(_pedir_senha()))
        banco.encerrar_sessoes_do_usuario(existente["id"])
        print("Senha alterada; as sessões abertas foram encerradas.")
    else:
        ativo = args.comando == "ativar"
        banco.atualizar_usuario(existente["id"], ativo=ativo)
        if not ativo:
            banco.encerrar_sessoes_do_usuario(existente["id"])
        print(f"Usuário '{login}' {'ativado' if ativo else 'desativado'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
