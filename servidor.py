"""
servidor.py - Sobe o Sentinela completo: serviço de visão + API + PWA.

LÓGICA GERAL
------------
1. Abre o banco SQLite (cria as tabelas na 1ª vez) e cadastra a câmera da --fonte.
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
import threading

import uvicorn
from dotenv import load_dotenv

faulthandler.enable()  # mostra a pilha se uma biblioteca nativa derrubar o processo
load_dotenv()

from sentinela_api.app import criar_app  # noqa: E402
from sentinela_api.banco import Banco  # noqa: E402
from sentinela_api.notificador_remoto import NotificadorRemoto  # noqa: E402
from sentinela_api.push import ServicoPush  # noqa: E402
from sentinela_api.vigia import VigiaCameras  # noqa: E402
from sentinela_api.servico_visao import ServicoRemoto, ServicoVisao  # noqa: E402

PASTA_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "dist")
TEMPO_MAX_ENCERRAMENTO_S = 5


class ServidorUvicorn(uvicorn.Server):
    """
    uvicorn com Ctrl+C garantido.

    Problema: no Ctrl+C o uvicorn cancela WebSocket/vídeo, mas depois espera o navegador
    fechar as conexões keep-alive; com a aba aberta isso nunca acontece e o terminal travava.
    Solução: 1º Ctrl+C -> desliga a câmera e pede encerramento normal; se em 5 s ainda não
    saiu, força a saída. 2º Ctrl+C -> sai na hora.
    """

    def __init__(self, config: uvicorn.Config, servico):
        super().__init__(config)
        self.servico = servico

    def handle_exit(self, sig, frame) -> None:
        if self.should_exit:  # segundo Ctrl+C
            print("\n[Sentinela] Saindo imediatamente.", flush=True)
            os._exit(1)
        print("\n[Sentinela] Encerrando... (Ctrl+C de novo para sair na hora)", flush=True)
        super().handle_exit(sig, frame)
        self.servico.parar()  # libera a câmera já no primeiro Ctrl+C
        relogio = threading.Timer(TEMPO_MAX_ENCERRAMENTO_S, self._forcar_saida)
        relogio.daemon = True  # se o encerramento normal terminar antes, o relógio morre junto
        relogio.start()

    @staticmethod
    def _forcar_saida() -> None:
        print("[Sentinela] Conexões do navegador não fecharam; encerramento forçado.", flush=True)
        os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinela - servidor (visão + API + PWA)")
    parser.add_argument("--fonte", default=os.getenv("CAMERA_FONTE", "0"), help="índice da webcam, RTSP ou vídeo")
    parser.add_argument("--camera", default=os.getenv("CAMERA_NOME", "Quarto 1"), help="nome exibido na interface")
    parser.add_argument("--local", default=os.getenv("CAMERA_LOCAL", "Térreo"), help="local da câmera")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 para acessar pelo celular na rede")
    parser.add_argument("--porta", type=int, default=8000)
    parser.add_argument("--banco", default="sentinela.db", help="arquivo SQLite (usado só sem Postgres no .env)")
    parser.add_argument("--painel", action="store_true", default=os.getenv("MODO_PAINEL", "0") == "1",
                        help="modo painel: só API, interface, login e push (sem câmera nem detecção). "
                             "Usado na VPS; a detecção roda em outro computador que grava no mesmo banco")
    args = parser.parse_args()

    exigir_login = os.getenv("LOGIN_OBRIGATORIO", "0") == "1"
    # Conferido ANTES de conectar no banco: uma configuração insegura não chega a tocar em nada.
    if not exigir_login and args.host not in ("127.0.0.1", "localhost", "::1"):
        # Sem login, qualquer um na rede poderia criar usuários, chaves de agente e apagar câmeras.
        if os.getenv("PERMITIR_REDE_SEM_LOGIN", "0") != "1":
            print("[Sentinela] RECUSADO: --host abre o painel na rede e o login está desligado.\n"
                  "            Defina LOGIN_OBRIGATORIO=1 no .env (recomendado) ou, só para teste numa rede\n"
                  "            confiável, PERMITIR_REDE_SEM_LOGIN=1.")
            raise SystemExit(2)
        print("[Sentinela] ATENÇÃO: acessível pela rede e SEM login (PERMITIR_REDE_SEM_LOGIN=1).")
    banco = Banco(args.banco)  # PostgreSQL se o .env tiver DATABASE_URL/PGHOST; senão SQLite local
    print(f"[Sentinela] Banco de dados: {banco.descricao}")
    camera = None if args.painel else banco.garantir_camera(args.camera, args.local, args.fonte)
    push = ServicoPush(banco)
    if not push.configurado:
        print("[Sentinela] Push desativado: defina VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY no .env "
              "(python -m sentinela_api.push --gerar-chaves).")
    whatsapp = NotificadorRemoto()  # no modo painel quem avisa é o painel, quando o agente envia o alerta
    if whatsapp.configurado:
        print(f"[Sentinela] WhatsApp: avisando o notificador em {whatsapp.url}")
        if os.getenv("WHATSAPP_URL"):
            print("[Sentinela] Atenção: WHATSAPP_URL também está definido; deixe vazio para não enviar em dobro.")
    else:
        print("[Sentinela] WhatsApp: NOTIFICADOR_URL/NOTIFICADOR_TOKEN não configurados (sem envio imediato).")
    if args.painel:
        servico = ServicoRemoto(banco)
        print("[Sentinela] Modo painel: sem câmera neste servidor (a detecção roda em outro computador).")
    else:
        servico = ServicoVisao(banco, camera, args.fonte, servico_push=push, notificador_remoto=whatsapp)
    servico.iniciar()
    vigia = VigiaCameras(banco, servico, push, whatsapp)  # modo painel: avisa câmera sem sinal (push e WhatsApp)
    vigia.iniciar()

    if not os.path.exists(os.path.join(PASTA_WEB, "index.html")):
        print("[Sentinela] Interface não compilada. Rode:  cd web && npm install && npm run build")

    # Cookie "Secure" só vai por HTTPS (ou localhost); com login ativo, é o padrão.
    cookie_seguro = os.getenv("COOKIE_SEGURO", "1" if exigir_login else "0") == "1"
    if exigir_login and banco.contar_usuarios() == 0:
        print("[Sentinela] ATENÇÃO: login obrigatório, mas não há usuários. Crie o administrador com:\n"
              "            python -m sentinela_api.usuarios criar --usuario admin --nome Administrador --papel ADMIN")
    print(f"[Sentinela] Abra http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.porta}")
    config = uvicorn.Config(criar_app(banco, servico, PASTA_WEB, push, exigir_login=exigir_login,
                                      cookie_seguro=cookie_seguro,
                                      pasta_fotos=os.getenv("PASTA_FOTOS", "alertas_queda"),
                                      notificador_remoto=whatsapp), host=args.host, port=args.porta,
                            log_level="warning", timeout_graceful_shutdown=2)
    try:
        ServidorUvicorn(config, servico).run()
    except KeyboardInterrupt:
        pass
    finally:
        servico.parar()
        print("[Sentinela] Servidor encerrado.", flush=True)


if __name__ == "__main__":
    main()
