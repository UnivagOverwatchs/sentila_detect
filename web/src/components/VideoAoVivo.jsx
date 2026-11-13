/*
 * VideoAoVivo.jsx - Vídeo da câmera montado quadro a quadro.
 *
 * Por que não <img src="/api/video"> (MJPEG)?
 *   O stream MJPEG mantém uma conexão HTTP aberta para sempre, e o navegador nem sempre a
 *   fecha ao trocar de tela. Como ele permite só ~6 conexões por servidor, depois de algumas
 *   trocas a interface inteira congelava esperando vaga.
 *
 * Como funciona aqui:
 *   1. busca /api/quadro (1 JPEG) com fetch;
 *   2. só pede o próximo depois que o anterior chegou (sem acumular pedidos se a rede ficar lenta);
 *   3. pausa quando a aba está em segundo plano (economiza CPU e rede);
 *   4. ao sair da tela, cancela tudo e libera a memória das imagens.
 */
import { useEffect, useState } from "react";
import { api } from "../services/api.js";

const TEMPO_LIMITE_QUADRO_MS = 5000;
const FALHAS_PARA_AVISAR = 5;

export function VideoAoVivo({ alt, fps = 12, cameraId, aoMudarDisponibilidade }) {
  const [src, setSrc] = useState(null);

  useEffect(() => {
    let ativo = true;
    let temporizador;
    let falhas = 0;
    const urls = []; // URLs de blob ainda em uso (liberadas com atraso para não piscar)
    const controle = new AbortController();

    async function proximoQuadro() {
      if (!ativo) return;
      const inicio = performance.now();
      if (document.visibilityState === "visible") {
        try {
          // Cada quadro tem no máximo 5 s: um pedido "pendurado" não congela o vídeo (conta como falha e segue).
          const limite = AbortSignal.any && AbortSignal.timeout
            ? AbortSignal.any([controle.signal, AbortSignal.timeout(TEMPO_LIMITE_QUADRO_MS)])
            : controle.signal;
          const resposta = await fetch(api.urlQuadro(cameraId), { cache: "no-store", signal: limite });
          if (!resposta.ok) throw new Error(String(resposta.status));
          const url = URL.createObjectURL(await resposta.blob());
          if (!ativo) return URL.revokeObjectURL(url);
          setSrc(url);
          urls.push(url);
          while (urls.length > 2) URL.revokeObjectURL(urls.shift());
          if (falhas >= FALHAS_PARA_AVISAR) aoMudarDisponibilidade?.(true);
          falhas = 0;
        } catch {
          if (!ativo) return;
          falhas += 1;
          if (falhas === FALHAS_PARA_AVISAR) aoMudarDisponibilidade?.(false);
        }
      }
      // Mantém o ritmo desejado descontando o tempo que o quadro levou para chegar.
      const espera = Math.max(0, 1000 / fps - (performance.now() - inicio));
      temporizador = setTimeout(proximoQuadro, falhas ? 1000 : espera);
    }

    proximoQuadro();
    return () => {
      ativo = false;
      clearTimeout(temporizador);
      controle.abort();
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [fps, cameraId, aoMudarDisponibilidade]);

  return src ? <img src={src} alt={alt} /> : null;
}
