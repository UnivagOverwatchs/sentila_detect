/*
 * Painel.jsx - Painel de monitoramento (Figura 10; RF08).
 *   - Vídeo ao vivo: UMA câmera grande (com seletor) ou GRADE com todas as câmeras ao mesmo tempo.
 *   - Indicadores: câmeras ativas, alertas pendentes, sensibilidade, pessoas em cena.
 *   - Alertas recentes com ação rápida "Resolver".
 */
import { useState } from "react";
import { VideoAoVivo } from "../components/VideoAoVivo.jsx";
import { VideoLocal } from "../components/VideoLocal.jsx";
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

/** online: true = agente falando; false = sumiu; null = ninguém avisa por ela (computador antigo grava direto no banco). */
export function rotuloCamera(c) {
  if (!c) return { texto: "OFFLINE", classe: "" };
  if (!c.ativa) return { texto: "PAUSADA", classe: "" };
  if (c.online === true && c.deteccao === false) return { texto: "SÓ VÍDEO", classe: "vivo" }; // transmite, mas não detecta queda
  if (c.online === true) return { texto: "AO VIVO", classe: "vivo" };
  if (c.online === false) return { texto: "OFFLINE", classe: "" };
  return { texto: "SEM AGENTE", classe: "" };
}

function PontoCamera({ camera }) {
  const classe = !camera.ativa ? "off" : camera.online === true ? "on" : camera.online === false ? "erro" : "off";
  return <span className={`ponto ponto--${classe === "on" ? "on" : classe === "erro" ? "queda" : "off"}`} />;
}

export function Painel({
  status,
  conectado,
  cameras: cameraDoCadastro,
  cameraId,
  aoSelecionarCamera,
  modo,
  aoMudarModo,
  alertas,
  aoTratar,
  cameraDoAparelho,
}) {
  const [videoDisponivel, setVideoDisponivel] = useState(true);
  // Câmera deste aparelho: mostra direto da câmera (resolução cheia, sem atraso) em vez de buscar no servidor.
  const ehLocal = (c) => cameraDoAparelho?.fase === "transmitindo" && c?.id != null && cameraDoAparelho.cameraId === c.id;
  const recentes = alertas.slice(0, 6);
  // O status traz o estado de cada câmera; sem ele (servidor antigo), usamos só o cadastro.
  const estados = status?.cameras?.length
    ? status.cameras
    : cameraDoCadastro.map((c) => ({ ...c, online: status?.camera_online ?? null, fps: status?.fps ?? 0, pessoas: status?.pessoas ?? 0 }));
  const selecionada = estados.find((c) => c.id === cameraId) ?? estados.find((c) => c.id === status?.camera_id) ?? estados[0];
  const varias = estados.length > 1;
  const emGrade = varias && modo === "grade";
  const selo = rotuloCamera(selecionada);

  return (
    <div className="grade-painel">
      <section className="cartao cartao--video">
        {varias && (
          <div className="seletor-cameras" role="toolbar" aria-label="Câmeras">
            <div className="seletor-cameras__lista">
              {estados.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`chip-camera ${!emGrade && selecionada?.id === c.id ? "ativo" : ""}`}
                  onClick={() => {
                    aoSelecionarCamera(c.id);
                    aoMudarModo("uma");
                  }}
                  title={c.local || c.nome}
                >
                  <PontoCamera camera={c} />
                  {c.nome}
                </button>
              ))}
            </div>
            <div className="alternador" role="group" aria-label="Modo de exibição">
              <button type="button" className={modo !== "grade" ? "ativo" : ""} onClick={() => aoMudarModo("uma")}>
                Uma
              </button>
              <button type="button" className={emGrade ? "ativo" : ""} onClick={() => aoMudarModo("grade")}>
                Todas
              </button>
            </div>
          </div>
        )}

        {emGrade ? (
          <div className="grade-cameras">
            {estados.map((c) => {
              const s = rotuloCamera(c);
              return (
                <button
                  key={c.id}
                  type="button"
                  className="tile-camera"
                  onClick={() => {
                    aoSelecionarCamera(c.id);
                    aoMudarModo("uma");
                  }}
                  title="Clique para ver só esta câmera"
                >
                  {ehLocal(c) ? (
                    <VideoLocal camera={cameraDoAparelho} esqueleto={false} />
                  ) : (
                    conectado && <VideoAoVivo cameraId={c.id} fps={3} alt={`Câmera ${c.nome}`} />
                  )}
                  <span className={`video__selo ${s.classe ? "video__selo--vivo" : ""}`}>{s.texto}</span>
                  <span className="video__camera">{c.nome}</span>
                  {c.estado === "alerta" && <span className="tile-camera__alerta">ALERTA</span>}
                </button>
              );
            })}
          </div>
        ) : (
          <div className="video">
            {ehLocal(selecionada) ? (
              <VideoLocal camera={cameraDoAparelho} />
            ) : conectado && (
              <VideoAoVivo
                cameraId={selecionada?.id}
                alt={`Câmera ao vivo - ${selecionada?.nome ?? ""}`}
                aoMudarDisponibilidade={setVideoDisponivel}
              />
            )}
            {!ehLocal(selecionada) && (!conectado || !videoDisponivel) && (
              <div className="video__vazio">
                <IconeCamera tamanho={32} />
                <span>{conectado ? "Vídeo indisponível, tentando de novo..." : "Conectando ao serviço de visão..."}</span>
              </div>
            )}
            <span className={`video__selo ${conectado && selo.classe ? "video__selo--vivo" : ""}`}>
              {conectado ? selo.texto : "OFFLINE"}
            </span>
            {selecionada && (
              <span className="video__camera">
                {selecionada.nome}
                {ehLocal(selecionada) && " · este aparelho (sem atraso)"}
              </span>
            )}
            <span className="video__rodape">
              Detecção em tempo real · MediaPipe Pose {selecionada?.online ? `· ${Math.round(selecionada.fps)} FPS` : ""}
            </span>
          </div>
        )}
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
        <Indicador
          rotulo={emGrade ? "Pessoas em cena (todas)" : "Pessoas em cena"}
          valor={status ? (emGrade ? estados.reduce((total, c) => total + (c.pessoas || 0), 0) : selecionada?.pessoas ?? status.pessoas ?? 0) : "–"}
          Icone={IconePessoas}
        />
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
