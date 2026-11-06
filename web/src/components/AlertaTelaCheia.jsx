/*
 * AlertaTelaCheia.jsx - Tela vermelha de emergência (Figura 13, à direita; UC03).
 *
 * Aparece por cima de tudo quando chega um alerta PENDENTE.
 * Ações (UC04 - Tratar alerta):
 *   - Ligar para emergência: abre o discador com o 1º contato cadastrado.
 *   - Ver câmera ao vivo: alterna entre a foto do momento e o vídeo atual.
 *   - Resolver / Marcar como falso alarme: fecha o alerta registrando o cuidador.
 */
import { useEffect, useState } from "react";
import { api } from "../services/api.js";
import { TITULO_TIPO, haQuantoTempo } from "../services/formato.js";
import { IconeAlerta, IconeCamera, IconeCheck, IconeImagem, IconeTelefone } from "./Icones.jsx";

export function AlertaTelaCheia({ alerta, contatoEmergencia, aoTratar, totalPendentes }) {
  const [aoVivo, setAoVivo] = useState(false);
  const [, setTique] = useState(0);
  const [enviando, setEnviando] = useState(false);
  const [semFoto, setSemFoto] = useState(false);

  // Atualiza o "há X s" a cada segundo.
  useEffect(() => {
    const id = setInterval(() => setTique((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Novo alerta: volta a mostrar a foto do momento.
  useEffect(() => {
    setAoVivo(false);
    setSemFoto(false);
  }, [alerta.id]);

  async function tratar(status) {
    setEnviando(true);
    try {
      await aoTratar(alerta, status);
    } finally {
      setEnviando(false);
    }
  }

  const titulo = alerta.tipo === "QUEDA" ? "Queda detectada" : "Pessoa no chão";
  const telefone = contatoEmergencia?.telefone?.replace(/[^\d+]/g, "");

  return (
    <div className="emergencia" role="alertdialog" aria-labelledby="emergencia-titulo" aria-live="assertive">
      <div className="emergencia__corpo">
        <div className="emergencia__icone">
          <IconeAlerta tamanho={44} />
        </div>
        <h2 id="emergencia-titulo">{titulo}</h2>
        <p className="emergencia__local">
          {alerta.camera_nome} · {haQuantoTempo(alerta.ocorrido_em)}
        </p>
        <p className="emergencia__detalhe">{TITULO_TIPO[alerta.tipo]}</p>

        <div className="emergencia__midia">
          {aoVivo ? (
            <img src={api.urlVideo()} alt={`Câmera ao vivo - ${alerta.camera_nome}`} />
          ) : semFoto ? (
            <span className="emergencia__sem-foto">Foto indisponível — use “Ver câmera ao vivo”</span>
          ) : (
            <img src={api.urlImagemAlerta(alerta.id)} alt="Foto do momento do alerta" onError={() => setSemFoto(true)} />
          )}
          <span className="emergencia__midia-rotulo">{aoVivo ? "● AO VIVO" : "Momento do alerta"}</span>
        </div>

        <div className="emergencia__acoes">
          {telefone ? (
            <a className="botao botao--branco" href={`tel:${telefone}`}>
              <IconeTelefone tamanho={18} />
              Ligar para {contatoEmergencia.nome}
            </a>
          ) : (
            <a className="botao botao--branco" href="tel:192">
              <IconeTelefone tamanho={18} />
              Ligar para SAMU (192)
            </a>
          )}
          <button className="botao botao--translucido" onClick={() => setAoVivo((v) => !v)}>
            {aoVivo ? <IconeImagem tamanho={18} /> : <IconeCamera tamanho={18} />}
            {aoVivo ? "Ver foto do momento" : "Ver câmera ao vivo"}
          </button>
          <button className="botao botao--translucido" disabled={enviando} onClick={() => tratar("RESOLVIDO")}>
            <IconeCheck tamanho={18} />
            Atendido — marcar como resolvido
          </button>
          <button className="emergencia__link" disabled={enviando} onClick={() => tratar("FALSO_ALARME")}>
            Marcar como falso alarme
          </button>
        </div>
        {totalPendentes > 1 && (
          <p className="emergencia__fila">+{totalPendentes - 1} alerta(s) pendente(s) na fila</p>
        )}
      </div>
    </div>
  );
}
