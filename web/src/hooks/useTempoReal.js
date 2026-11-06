/*
 * useTempoReal.js - Mantém a conexão WebSocket com a API.
 *
 * Entrega para as telas:
 *   status   -> último resumo (FPS, pessoas, pendentes, sensibilidade...)
 *   conectado-> se o WebSocket está aberto
 * e chama `aoReceberAlerta(alerta)` no instante em que um alerta novo nasce.
 *
 * Se a conexão cair (Wi-Fi, servidor reiniciado), reconecta sozinho com
 * espera crescente (1 s, 2 s, 4 s... até 15 s) para não sobrecarregar o servidor.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../services/api.js";

export function useTempoReal(aoReceberAlerta) {
  const [status, setStatus] = useState(null);
  const [conectado, setConectado] = useState(false);
  // Guardamos o callback em ref para não recriar o WebSocket a cada render.
  const callbackRef = useRef(aoReceberAlerta);
  callbackRef.current = aoReceberAlerta;

  useEffect(() => {
    let ws;
    let tentativa = 0;
    let temporizador;
    let encerrado = false;

    function conectar() {
      ws = new WebSocket(api.urlWebSocket());
      ws.onopen = () => {
        tentativa = 0;
        setConectado(true);
      };
      ws.onmessage = (evento) => {
        const msg = JSON.parse(evento.data);
        if (msg.tipo === "status") setStatus(msg.status);
        if (msg.tipo === "alerta") callbackRef.current?.(msg.alerta);
      };
      ws.onclose = () => {
        setConectado(false);
        if (encerrado) return;
        const espera = Math.min(1000 * 2 ** tentativa, 15000);
        tentativa += 1;
        // Sem conseguir reconectar: pode ser a sessão que expirou. Se o servidor exige login, volta para a tela de entrada.
        if (tentativa === 2) {
          api
            .eu()
            .then((r) => {
              if (r.login_obrigatorio && !r.usuario) window.dispatchEvent(new Event("sentinela:sessao-expirada"));
            })
            .catch(() => {});
        }
        temporizador = setTimeout(conectar, espera);
      };
    }

    conectar();
    return () => {
      encerrado = true;
      clearTimeout(temporizador);
      ws?.close();
    };
  }, []);

  return { status, conectado };
}
