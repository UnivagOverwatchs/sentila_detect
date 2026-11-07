"""
agentes.py - Gerencia os "agentes de visão": programas que rodam onde está a câmera e enviam alertas,
fotos e quadros ao painel. Cada agente tem uma chave própria (token).

Uso (no servidor do painel, com o .env configurado):
    python -m sentinela_api.agentes criar --nome "Quarto 1"     # mostra a chave UMA vez
    python -m sentinela_api.agentes listar
    python -m sentinela_api.agentes nova-chave --nome "Quarto 1"  # gera outra chave (a antiga deixa de valer)
    python -m sentinela_api.agentes revogar --nome "Quarto 1"
    python -m sentinela_api.agentes reativar --nome "Quarto 1"

A chave nunca fica gravada: o banco guarda só o SHA-256 dela. Se for perdida, gere uma nova.
"""

import argparse
import hashlib
import secrets
import sys
from typing import Optional

from dotenv import load_dotenv

from .banco import Banco

PREFIXO_TOKEN = "snt_"


def novo_token() -> str:
    return PREFIXO_TOKEN + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def main(argv=None, banco: Optional[Banco] = None) -> int:
    parser = argparse.ArgumentParser(description="Agentes de visão do Sentinela")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("listar")
    for nome in ("criar", "nova-chave", "revogar", "reativar"):
        sub.add_parser(nome).add_argument("--nome", required=True)
    args = parser.parse_args(argv)

    if banco is None:
        load_dotenv()
        banco = Banco()

    if args.comando == "listar":
        for a in banco.listar_agentes():
            visto = a["ultimo_contato"] or "nunca"
            print(f"{a['id']:>3}  {a['nome']:<24} {'ativo' if a['ativo'] else 'REVOGADO':<9} último contato: {visto}")
        return 0

    nome = args.nome.strip()
    if args.comando in ("criar", "nova-chave"):
        token = novo_token()
        if args.comando == "criar":
            if any(a["nome"] == nome for a in banco.listar_agentes()):
                print("Já existe um agente com esse nome. Use `nova-chave` para gerar outra chave.")
                return 1
            banco.criar_agente(nome, hash_token(token))
        elif not banco.trocar_token_do_agente(nome, hash_token(token)):
            print("Agente não encontrado.")
            return 1
        print(f"Agente '{nome}' pronto. Copie a chave abaixo AGORA: ela não será mostrada de novo.\n")
        print(token)
        print("\nNo computador da câmera, coloque no .env:  SENTINELA_TOKEN=<a chave acima>")
        return 0

    if not banco.definir_agente_ativo(nome, args.comando == "reativar"):
        print("Agente não encontrado.")
        return 1
    print(f"Agente '{nome}' {'reativado' if args.comando == 'reativar' else 'revogado'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
