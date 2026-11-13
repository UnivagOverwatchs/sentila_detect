/*
 * VideoLocal.jsx - Imagem da câmera DESTE aparelho, direto da câmera ("espelho"): resolução cheia e sem atraso.
 *
 * Por que não usar o VideoAoVivo aqui? Ele busca JPEGs no servidor (reduzidos e com o atraso da rede).
 * Quando a câmera é deste aparelho, a imagem já está aqui: basta ligar o MediaStream num <video>.
 *
 * LÓGICA
 *   - <video> mostra o stream; câmera frontal aparece espelhada (como um espelho), a traseira não.
 *   - <canvas> transparente por cima, do mesmo tamanho do vídeo, redesenha o esqueleto a cada quadro de tela
 *     (requestAnimationFrame) com o último resultado da detecção. O canvas não é espelhado por CSS: o controlador
 *     espelha só as posições, para o texto ("ID1 NORMAL 12°") continuar legível.
 */
import { useEffect, useRef } from "react";

export function VideoLocal({ camera, esqueleto = true, className = "" }) {
  const video = useRef(null);
  const tela = useRef(null);
  const espelhar = camera.facing === "user";

  useEffect(() => {
    if (video.current) video.current.srcObject = camera.stream ?? null;
  }, [camera.stream]);

  useEffect(() => {
    if (!esqueleto) return undefined;
    let quadro;
    const desenhar = () => {
      const v = video.current;
      const c = tela.current;
      if (v && c && v.videoWidth) {
        // Canvas no tamanho real do vídeo: com object-fit igual ao do <video>, os dois ficam alinhados.
        if (c.width !== v.videoWidth || c.height !== v.videoHeight) {
          c.width = v.videoWidth;
          c.height = v.videoHeight;
        }
        camera.desenharSobreposicao(c.getContext("2d"), c.width, c.height, espelhar);
      }
      quadro = requestAnimationFrame(desenhar);
    };
    quadro = requestAnimationFrame(desenhar);
    return () => cancelAnimationFrame(quadro);
  }, [esqueleto, espelhar, camera]);

  return (
    <div className={`video-local ${className}`}>
      <video ref={video} autoPlay muted playsInline className={espelhar ? "video-local--espelho" : ""} />
      {esqueleto && <canvas ref={tela} aria-hidden="true" />}
    </div>
  );
}
