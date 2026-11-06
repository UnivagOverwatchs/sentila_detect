/*
 * Painel.jsx - Painel de monitoramento (Figura 10; RF08).
 *   - Vídeo ao vivo com o esqueleto/estado desenhado pelo serviço de visão.
 *   - Indicadores: câmeras ativas, alertas pendentes, sensibilidade, pessoas em cena.
 *   - Alertas recentes com ação rápida "Resolver".
 */
import { useState } from "react";
import { api } from "../services/api.js";
import { dia, hora, TITULO_TIPO } from "../services/formato.js";
import { IconeAtividade, IconeCamera, IconeCheck, IconePessoas, IconeSino } from "../components/Icones.jsx";

function Indicador({ rotulo, valor, Icone, destaque }) {
  return (
    <div className={`indicador ${destaque ? "indicador--destaque" : ""}`}>
      <span className="indicador__icone">
        <Icone tamanho={16} />
      </span>
      <span className="indicador__rotulo">{rotulo}</span>
      <strong className="indicador__valor">{valor}</strong>
    </div>
  );
}

export function Painel({ status, conectado, camera, alertas, aoTratar }) {
  const [erroVideo, setErroVideo] = useState(false);
  const recentes = alertas.slice(0, 6);
  const online = conectado && status?.camera_online;
  const pausada = status && !status.camera_ativa;

  return (
    <div className="grade-painel">
      <section className="cartao cartao--video">
        <div className="video">
          {conectado && !erroVideo ? (
            // MJPEG: o navegador atualiza a imagem sozinho a cada quadro recebido.
            <img src={api.urlVideo()} alt={`Câmera ao vivo - ${camera?.nome ?? ""}`} onError={() => setErroVideo(true)} />
          ) : (
            <div className="video__vazio">
              <IconeCamera tamanho={32} />
              <span>{conectado ? "Vídeo indisponível" : "Conectando ao serviço de visão..."}</span>
              {erroVideo && (
                <button className="botao botao--pequeno" onClick={() => setErroVideo(false)}>
                  Tentar de novo
                </button>
              )}
            </div>
          )}
          <span className={`video__selo ${online && !pausada ? "video__selo--vivo" : ""}`}>
            {pausada ? "PAUSADA" : online ? "AO VIVO" : "OFFLINE"}
          </span>
          {camera && <span className="video__camera">{camera.nome}</span>}
          <span className="video__rodape">
            Detecção em tempo real · MediaPipe Pose {status ? `· ${Math.round(status.fps)} FPS` : ""}
          </span>
        </div>
      </section>

      <div className="indicadores">
        <Indicador
          rotulo="Câmeras ativas"
          valor={status ? `${status.cameras_ativas}/${status.cameras_total}` : "–"}
          Icone={IconeCamera}
        />
        <Indicador
          rotulo="Alertas pendentes"
          valor={status?.pendentes ?? "–"}
          Icone={IconeSino}
          destaque={status?.pendentes > 0}
        />
        <Indicador rotulo="Sensibilidade" valor={status?.sensibilidade_rotulo ?? "–"} Icone={IconeAtividade} />
        <Indicador rotulo="Pessoas em cena" valor={status?.pessoas ?? "–"} Icone={IconePessoas} />
      </div>

      <section className="cartao cartao--alertas">
        <header className="cartao__cabecalho">
          <h2>Alertas recentes</h2>
          <p>Clique para marcar como resolvido</p>
        </header>
        {recentes.length === 0 ? (
          <div className="vazio">
            <IconeCheck tamanho={22} />
            <span>Nenhum alerta registrado. Tudo tranquilo.</span>
          </div>
        ) : (
          <ul className="lista-alertas">
            {recentes.map((a) => (
              <li key={a.id} className="lista-alertas__item">
                <span className={`ponto ponto--${a.status === "PENDENTE" ? (a.tipo === "QUEDA" ? "queda" : "chao") : "ok"}`} />
                <div className="lista-alertas__texto">
                  <strong>{TITULO_TIPO[a.tipo]}</strong>
                  <small>
                    {a.camera_nome} · {dia(a.ocorrido_em)} {hora(a.ocorrido_em)}
                  </small>
                </div>
                {a.status === "PENDENTE" ? (
                  <button className="botao botao--pequeno" onClick={() => aoTratar(a, "RESOLVIDO")}>
                    Resolver
                  </button>
                ) : (
                  <span className={`etiqueta-status etiqueta-status--${a.status.toLowerCase()}`}>
                    {a.status === "RESOLVIDO" ? (
                      <>
                        <IconeCheck tamanho={12} /> Resolvido
                      </>
                    ) : (
                      "Falso alarme"
                    )}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
