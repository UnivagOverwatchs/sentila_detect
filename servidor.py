"""
servidor.py - Sobe o Sentinela completo: serviço de visão + API + PWA.

LÓGICA GERAL
------------
1. Conecta ao PostgreSQL (tabelas só com --criar-tabelas) e cadastra a câmera da --fonte.
2. Inicia o ServicoVisao em uma thread (pose + lógica de queda + gravação de alertas).
3. Sobe a API FastAPI com uvicorn, que também entrega a PWA já compilada (web/dist).

Uso:
    python servidor.py                         # webcam 0, só neste computador
    python servidor.py --fonte 1 --camera "Quarto 2" --local "1º andar"
    python servidor.py --host 0.0.0.0          # libera para celulares na mesma rede (sem login ainda!)

Depois abra http://localhost:8000
"""

import argparse
import faulthandler
import os

import uvicorn
from dotenv import load_dotenv

faulthandler.enable()  # mostra a pilha se uma biblioteca nativa derrubar o processo
load_dotenv()

from sentinela_api.app import criar_app  # noqa: E402
from sentinela_api.banco import Banco  # noqa: E402
from sentinela_api.push import ServicoPush  # noqa: E402
from sentinela_api.servico_visao import ServicoVisao  # noqa: E402

PASTA_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "dist")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinela - servidor (visão + API + PWA)")
    parser.add_argument("--fonte", default=os.getenv("CAMERA_FONTE", "0"), help="índice da webcam, RTSP ou vídeo")
    parser.add_argument("--camera", default=os.getenv("CAMERA_NOME", "Quarto 1"), help="nome exibido na interface")
    parser.add_argument("--local", default=os.getenv("CAMERA_LOCAL", "Térreo"), help="local da câmera")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 para acessar pelo celular na rede")
    parser.add_argument("--porta", type=int, default=8000)
    parser.add_argument("--criar-tabelas", action="store_true", help="cria as tabelas no PostgreSQL e encerra (só quando pedido)")
    args = parser.parse_args()

    banco = Banco()  # PostgreSQL, conforme POSTGRES_* do .env
    if args.criar_tabelas:
        banco.criar_tabelas()
        print("[Sentinela] Tabelas criadas.")
        banco.fechar()
        return
    camera = banco.garantir_camera(args.camera, args.local, args.fonte)
    push = ServicoPush(banco)
    if not push.configurado:
        print("[Sentinela] Push desativado: defina VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY no .env "
              "(python -m sentinela_api.push --gerar-chaves).")
    servico = ServicoVisao(banco, camera, args.fonte, servico_push=push)
    servico.iniciar()

    if not os.path.exists(os.path.join(PASTA_WEB, "index.html")):
        print("[Sentinela] Interface não compilada. Rode:  cd web && npm install && npm run build")

    print(f"[Sentinela] Abra http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.porta}")
    try:
        uvicorn.run(criar_app(banco, servico, PASTA_WEB, push), host=args.host, port=args.porta, log_level="warning")
    finally:
        servico.parar()
        banco.fechar()


if __name__ == "__main__":
    main()
