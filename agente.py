"""
agente.py - Agente de visão do Sentinela: detecta quedas na câmera e envia ao painel (VPS) por HTTPS.

Roda onde a câmera é alcançável (um computador pequeno no local, ou outro lugar com acesso à câmera).
O vídeo NUNCA sai daqui: só o alerta, uma foto do momento e um quadro por segundo para a tela "ao vivo".

Preparação (uma vez), no servidor do painel:
    python -m sentinela_api.agentes criar --nome "Quarto 1"     # mostra a chave UMA vez
No computador do agente, no .env:
    SENTINELA_URL=https://painel.sentinelaunivag.com.br
    SENTINELA_TOKEN=<a chave acima>
    CAMERA_FONTE=0                      # 0 = webcam; ou rtsp://usuario:senha@IP:554/caminho
Uso:
    python agente.py                    # usa o .env
    python agente.py --camera "Quarto 1" --local "Térreo"

A chave vai SEMPRE pelo .env, nunca na linha de comando (a linha de comando aparece na lista de processos).
Se a internet cair, os alertas ficam na pasta fila_agente/ e seguem quando ela voltar.
"""

import argparse
import faulthandler
import os
import sys
import time

from dotenv import load_dotenv

faulthandler.enable()
load_dotenv()

from sentinela_api.cliente_agente import BancoRemoto, ClienteAgente, ErroDefinitivo, Sincronizador  # noqa: E402
from sentinela_api.sensibilidade import aplicar_sensibilidade  # noqa: E402
from sentinela_api.servico_visao import ServicoVisao  # noqa: E402
from sentinela_pose.alertas import NotificadorAlertas  # noqa: E402


def conectar(cliente: ClienteAgente, nome: str, local: str, tentativas_ate: float = 300.0) -> dict:
    """Registra a câmera no painel, esperando a rede/painel voltarem se preciso."""
    espera, limite = 2.0, time.monotonic() + tentativas_ate
    while True:
        try:
            return cliente.registrar_camera(nome, local)
        except ErroDefinitivo as erro:
            sys.exit(f"[Agente] o painel recusou o cadastro da câmera: {erro}\n"
                     "         Confira SENTINELA_TOKEN (a chave pode ter sido revogada).")
        except Exception as erro:  # noqa: BLE001 - rede, DNS, 5xx
            if time.monotonic() > limite:
                sys.exit(f"[Agente] não consegui falar com o painel: {erro}")
            print(f"[Agente] painel indisponível ({erro.__class__.__name__}); tentando de novo em {espera:.0f} s")
            time.sleep(espera)
            espera = min(espera * 2, 30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinela - agente de visão")
    parser.add_argument("--url", default=os.getenv("SENTINELA_URL", ""), help="endereço do painel (https://...)")
    parser.add_argument("--fonte", default=os.getenv("CAMERA_FONTE", "0"), help="índice da webcam, RTSP ou vídeo")
    parser.add_argument("--camera", default=os.getenv("CAMERA_NOME", "Quarto 1"), help="nome exibido no painel")
    parser.add_argument("--local", default=os.getenv("CAMERA_LOCAL", "Térreo"), help="local da câmera")
    args = parser.parse_args()

    token = os.getenv("SENTINELA_TOKEN", "")
    if not args.url or not token:
        sys.exit("Defina SENTINELA_URL e SENTINELA_TOKEN no .env (a chave se cria com: "
                 "python -m sentinela_api.agentes criar --nome ...).")
    if not args.url.startswith("https://") and "localhost" not in args.url and "127.0.0.1" not in args.url:
        sys.exit("SENTINELA_URL precisa começar com https:// (a chave não pode trafegar sem criptografia).")

    cliente = ClienteAgente(args.url, token)
    if os.getenv("AGENTE_FORCAR_IPV4", "0") == "1":  # redes onde o IPv6 trava (medido: 40 s por chamada)
        from sentinela_api.push import sessao_ipv4
        cliente.sessao = sessao_ipv4()

    camera = conectar(cliente, args.camera, args.local)
    print(f"[Agente] câmera '{camera['nome']}' registrada no painel (id {camera['id']}).")
    aplicar_sensibilidade_inicial = camera.get("sensibilidade")

    banco = BancoRemoto(cliente, pasta_fila=os.getenv("PASTA_FILA", "fila_agente"),
                        guardar_fotos=os.getenv("AGENTE_GUARDAR_FOTOS", "0") == "1")
    banco.iniciar()
    servico = ServicoVisao(banco, camera, args.fonte,
                           notificador=NotificadorAlertas(pasta=os.getenv("PASTA_FOTOS", "alertas_queda")))
    if aplicar_sensibilidade_inicial is not None:
        aplicar_sensibilidade(servico.cfg_queda, aplicar_sensibilidade_inicial)
    sincronizador = Sincronizador(cliente, servico, camera["id"], aplicar_sensibilidade)
    servico.iniciar()
    sincronizador.iniciar()
    print("[Agente] detectando. Ctrl+C para parar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        sincronizador.parar()
        servico.parar()
        banco.parar()
        print("[Agente] encerrado.")


if __name__ == "__main__":
    main()
