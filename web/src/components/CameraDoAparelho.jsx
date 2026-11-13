/*
 * CameraDoAparelho.jsx - "Usar a câmera deste aparelho": o celular ou o computador vira uma câmera do sistema.
 * O navegador pede a permissão da câmera, igual ao pedido de notificações.
 *
 * A detecção de queda roda AQUI, na página (MediaPipe + detectorQueda.js). Se o modelo não carregar, a tela diz com todas
 * as letras que a câmera só transmite e o painel marca "SÓ VÍDEO", para ninguém achar que há proteção onde não há.
 */
import { useState } from "react";
import { IconeCamera } from "./Icones.jsx";
import { VideoLocal } from "./VideoLocal.jsx";
import { nomeDoAparelho } from "../services/push.js";

export function CameraDoAparelho({ camera }) {
  const [nome, setNome] = useState(`Câmera ${nomeDoAparelho()}`);
  const [local, setLocal] = useState("");
  const [facing, setFacing] = useState("user");
  const { fase, erro, assistindo, fps, pausada, suportado, iniciar, parar, deteccao, pessoas, achadas, ultimoAlerta, processador, msDeteccao } = camera;
  const ligada = fase === "transmitindo";
  const ocupada = fase === "pedindo" || fase === "conectando";

  return (
    <section className="cartao">
      <header className="cartao__cabecalho">
        <h2>Usar a câmera deste aparelho</h2>
        <p>O celular ou o computador vira uma câmera do sistema, com vídeo ao vivo no painel. O navegador vai pedir a permissão.</p>
      </header>

      {!suportado ? (
        <p className="erro">Este navegador não permite usar a câmera (precisa de HTTPS e de um navegador atual).</p>
      ) : ligada || ocupada ? (
        <>
          <div className="previa-camera">
            {ligada ? <VideoLocal camera={camera} /> : <span>Aguardando a permissão da câmera…</span>}
          </div>
          <p className="dica">
            <IconeCamera tamanho={14} /> {ligada ? `Transmitindo "${camera.nome}"` : "Conectando…"}
            {ligada && ` · ${fps} quadros/s${assistindo ? " (alguém está assistindo)" : " (ninguém assistindo: modo econômico)"}`}
            {pausada && " · pausada no painel"}
          </p>
          {ligada && (
            <p className={deteccao === "indisponivel" ? "erro" : "dica"} role="status">
              {deteccao === "carregando" && "Carregando a detecção de queda… (só na primeira vez, pode levar alguns segundos)"}
              {deteccao === "ativa" && `Detecção de queda ligada (${processador}, ${msDeteccao} ms por análise) · ${pessoas} ${pessoas === 1 ? "pessoa" : "pessoas"} em cena` +
                (achadas > pessoas ? ` · ${achadas - pessoas} vista(s) sem o tronco inteiro na imagem (não contam)` : "")}
              {deteccao === "indisponivel" && "A detecção de queda não carregou neste aparelho: a câmera só transmite vídeo e NÃO está protegendo."}
              {ultimoAlerta && ` · último alerta: ${ultimoAlerta.tipo === "queda" ? "queda" : "pessoa no chão"} às ${new Date(ultimoAlerta.quando).toLocaleTimeString("pt-BR")}`}
            </p>
          )}
          <button className="botao botao--fantasma" onClick={parar} disabled={ocupada}>
            Parar
          </button>
        </>
      ) : (
        <form
          className="form-usuario"
          onSubmit={(e) => {
            e.preventDefault();
            iniciar({ nome, local, facing });
          }}
        >
          <input required placeholder="Nome da câmera" value={nome} onChange={(e) => setNome(e.target.value)} maxLength={80} />
          <input placeholder="Local (opcional)" value={local} onChange={(e) => setLocal(e.target.value)} maxLength={60} />
          <select value={facing} onChange={(e) => setFacing(e.target.value)} aria-label="Qual câmera">
            <option value="user">Câmera frontal (ou webcam)</option>
            <option value="environment">Câmera traseira</option>
          </select>
          <button className="botao" type="submit">
            Usar a câmera deste aparelho
          </button>
          {erro && (
            <p className="erro" role="alert">
              {erro}
            </p>
          )}
        </form>
      )}

      <div className="aviso-camera">
        <strong>Antes de usar:</strong> mantenha a <b>tela ligada</b> e esta página <b>aberta</b> (o aparelho para de enviar se o
        navegador for para segundo plano). A queda é detectada <b>neste aparelho</b>: ele precisa estar parado, com a câmera
        apontada para o ambiente e com boa luz. Para vigiar de forma contínua, prefira uma câmera fixa com o agente.
      </div>
    </section>
  );
}
