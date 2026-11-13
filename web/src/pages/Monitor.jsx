/*
 * Monitor.jsx - Tela de MONITORAMENTO para o cliente (ex.: TV na sala da equipe, apresentação do projeto).
 *
 * Mostra só o essencial, em letras grandes: cada câmera vira um quadro que responde
 * "o idoso está bem ou caiu?". Nada de configurações aqui.
 *
 * LÓGICA (situacaoDoQuadro)
 *   1. Há alerta PENDENTE dessa câmera?        -> QUEDA DETECTADA / PESSOA NO CHÃO (vermelho piscando, foto, botões).
 *   2. A detecção ao vivo diz "alerta"?          -> QUEDA DETECTADA (o alerta está sendo gravado neste instante).
 *   3. A detecção ao vivo diz "atencao"?         -> VERIFICANDO (amarelo: pessoa caindo/no chão, ainda confirmando).
 *   4. Câmera sem notícia (offline/nunca ligou)? -> SEM SINAL (cinza: não dá para garantir nada).
 *   5. Senão                                      -> TUDO BEM (verde).
 * Câmeras desativadas não aparecem. A faixa do topo resume tudo (quantas quedas, quantas câmeras ok).
 * "Tela cheia" usa a Fullscreen API só neste bloco, para deixar aberto numa TV.
 */
import { useEffect, useRef, useState } from "react";
import { FiguraEmPe, FiguraQueda, FiguraSemSinal } from "../components/Pictogramas.jsx";
import { api } from "../services/api.js";
import { haQuantoTempo, hora } from "../services/formato.js";

export function situacaoDoQuadro(camera, estado, pendente) {
  if (pendente) return pendente.tipo === "QUEDA" ? "queda" : "chao";
  if (estado?.online && estado.estado === "alerta") return "queda";
  if (estado?.online && estado.estado === "atencao") return "atencao";
  if (!estado?.online) return "sem-sinal";
  return "ok";
}

const TEXTOS = {
  queda: { titulo: "QUEDA DETECTADA", Figura: FiguraQueda },
  chao: { titulo: "PESSOA NO CHÃO", Figura: FiguraQueda },
  atencao: { titulo: "VERIFICANDO…", Figura: FiguraQueda },
  "sem-sinal": { titulo: "SEM SINAL", Figura: FiguraSemSinal },
  ok: { titulo: "TUDO BEM", Figura: FiguraEmPe },
};

function Quadro({ camera, estado, pendente, aoTratar }) {
  const [enviando, setEnviando] = useState(false);
  const [semFoto, setSemFoto] = useState(false);
  const situacao = situacaoDoQuadro(camera, estado, pendente);
  const { titulo, Figura } = TEXTOS[situacao];
  const emAlerta = situacao === "queda" || situacao === "chao";

  async function tratar(status) {
    setEnviando(true);
    try {
      await aoTratar(pendente, status);
    } finally {
      setEnviando(false);
    }
  }

  let detalhe = "";
  if (pendente) detalhe = `às ${hora(pendente.ocorrido_em)} · ${haQuantoTempo(pendente.ocorrido_em)}`;
  else if (situacao === "ok") detalhe = estado?.pessoas ? `${estado.pessoas} ${estado.pessoas === 1 ? "pessoa" : "pessoas"} em cena` : "Ninguém em cena";
  else if (situacao === "sem-sinal") detalhe = estado?.online === false ? "A câmera parou de enviar imagens" : "Aguardando a câmera conectar";
  else if (situacao === "atencao") detalhe = "Movimento suspeito, confirmando…";
  else detalhe = "Registrando o alerta…";

  return (
    <article className={`quadro-monitor quadro-monitor--${situacao}`} aria-live={emAlerta ? "assertive" : "polite"}>
      <header className="quadro-monitor__camera">
        <strong>{camera.nome}</strong>
        {camera.local && <span>{camera.local}</span>}
      </header>

      <div className="quadro-monitor__corpo">
        {pendente?.imagem && !semFoto ? (
          <img className="quadro-monitor__foto" src={api.urlImagemAlerta(pendente.id)} alt={`Momento do alerta em ${camera.nome}`} onError={() => setSemFoto(true)} />
        ) : (
          <Figura className="quadro-monitor__figura" tamanho={140} />
        )}
        <p className="quadro-monitor__titulo">{titulo}</p>
        <p className="quadro-monitor__detalhe">{detalhe}</p>
      </div>

      {pendente && (
        <div className="quadro-monitor__acoes">
          <button className="botao botao--branco" disabled={enviando} onClick={() => tratar("RESOLVIDO")}>
            Atendido
          </button>
          <button className="botao botao--translucido" disabled={enviando} onClick={() => tratar("FALSO_ALARME")}>
            Falso alarme
          </button>
        </div>
      )}
    </article>
  );
}

export function Monitor({ cameras, estadoCameras = [], alertas, aoTratar, conectado }) {
  const area = useRef(null);
  const [telaCheia, setTelaCheia] = useState(false);
  const [agora, setAgora] = useState(() => new Date());

  // Relógio (e o "há X min" dos quadros) atualizando a cada segundo.
  useEffect(() => {
    const id = setInterval(() => setAgora(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const aoMudar = () => setTelaCheia(document.fullscreenElement === area.current);
    document.addEventListener("fullscreenchange", aoMudar);
    return () => document.removeEventListener("fullscreenchange", aoMudar);
  }, []);

  function alternarTelaCheia() {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else area.current?.requestFullscreen?.().catch(() => {});
  }

  const ativas = cameras.filter((c) => c.ativa);
  const quadros = ativas.map((c) => {
    const estado = estadoCameras.find((e) => e.id === c.id);
    // Lista de alertas vem do mais novo para o mais antigo: o 1º pendente é o mais recente.
    const pendente = alertas.find((a) => a.camera_id === c.id && a.status === "PENDENTE");
    return { camera: c, estado, pendente, situacao: situacaoDoQuadro(c, estado, pendente) };
  });
  const emAlerta = quadros.filter((q) => q.situacao === "queda" || q.situacao === "chao").length;
  const semSinal = quadros.filter((q) => q.situacao === "sem-sinal").length;

  let faixa;
  if (!conectado) faixa = { classe: "faixa-monitor--off", texto: "Sem conexão com o servidor", sub: "As informações podem estar desatualizadas" };
  else if (emAlerta) faixa = { classe: "faixa-monitor--alerta", texto: emAlerta === 1 ? "ATENÇÃO: 1 queda detectada" : `ATENÇÃO: ${emAlerta} quedas detectadas`, sub: "Vá até o local e marque como atendido" };
  else if (ativas.length === 0) faixa = { classe: "faixa-monitor--off", texto: "Nenhuma câmera ativa", sub: "Cadastre ou ative uma câmera na aba Câmeras" };
  else faixa = {
    classe: "faixa-monitor--ok",
    texto: "Tudo tranquilo",
    sub: semSinal ? `${ativas.length - semSinal} de ${ativas.length} câmeras funcionando · ${semSinal} sem sinal` : `${ativas.length} ${ativas.length === 1 ? "câmera vigiando" : "câmeras vigiando"}`,
  };

  return (
    <div ref={area} className={`monitor ${telaCheia ? "monitor--cheia" : ""}`}>
      <div className={`faixa-monitor ${faixa.classe}`} role="status">
        <div>
          <p className="faixa-monitor__texto">{faixa.texto}</p>
          <p className="faixa-monitor__sub">{faixa.sub}</p>
        </div>
        <div className="faixa-monitor__direita">
          <span className="faixa-monitor__relogio">{agora.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
          <button type="button" className="botao botao--translucido" onClick={alternarTelaCheia}>
            {telaCheia ? "Sair da tela cheia" : "Tela cheia"}
          </button>
        </div>
      </div>

      <div className="grade-monitor">
        {quadros.map((q) => (
          <Quadro key={q.camera.id} camera={q.camera} estado={q.estado} pendente={q.pendente} aoTratar={aoTratar} />
        ))}
      </div>
    </div>
  );
}
