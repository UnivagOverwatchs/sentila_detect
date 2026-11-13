/*
 * AdicionarCamera.jsx - Assistente "Adicionar câmera" (só administrador).
 *
 * LÓGICA
 *   Passo 1: escolher o TIPO de câmera.
 *     - "Este aparelho": o celular/computador que está com o painel aberto vira câmera (CameraDoAparelho).
 *     - "Câmera fixa ou IP": uma webcam ou câmera IP ligada a um computador que roda o agente.py.
 *   Passo 2 (câmera fixa): nome, local, de onde vem a imagem (webcam ou endereço RTSP) e qual computador.
 *     - Computador novo: o painel cria a chave do agente e monta o .env completo para copiar.
 *     - Computador que já tem agente: só o comando para abrir mais uma câmera nele.
 *   Passo 3: instruções prontas para copiar e um indicador que fica verde quando a câmera conecta
 *            (o tempo real lista as câmeras cadastradas; quando aparece uma com esse nome e online, deu certo).
 *
 * A chave do agente aparece UMA vez (o servidor guarda só o hash).
 */
import { useEffect, useState } from "react";
import { CameraDoAparelho } from "./CameraDoAparelho.jsx";
import { copiarTexto } from "./AgentesCamera.jsx";
import { IconeCamera, IconeFechar } from "./Icones.jsx";
import { api } from "../services/api.js";

// Mesma regra do servidor para nomes de agente (letras, números, sublinhado, espaço, ponto e hífen).
const NOME_AGENTE_VALIDO = /^[\p{L}\p{N}_ .-]{1,80}$/u;
// Aspas quebrariam o comando no terminal; o resto o agente aceita.
const semAspas = (texto) => texto.replace(/["“”]/g, "").trim();

export function AdicionarCamera({ cameras, estadoCameras = [], cameraDoAparelho, aoFechar, aoCriarAgente }) {
  const [tipo, setTipo] = useState(null); // null | "aparelho" | "fixa"
  const [form, setForm] = useState({ nome: "", local: "", origem: "webcam", indice: "0", rtsp: "", computador: "novo", nomeComputador: "" });
  const [computadores, setComputadores] = useState([]);
  const [resultado, setResultado] = useState(null); // { nome, env, comando }
  const [erro, setErro] = useState("");
  const [copiado, setCopiado] = useState("");

  useEffect(() => {
    if (tipo !== "fixa") return;
    api
      .agentes()
      .then((lista) => setComputadores(lista.filter((a) => a.ativo && !a.nome.startsWith("Navegador ["))))
      .catch(() => setComputadores([]));
  }, [tipo]);

  const mudar = (campo) => (e) => setForm({ ...form, [campo]: e.target.value });

  async function gerar(e) {
    e.preventDefault();
    setErro("");
    const nome = semAspas(form.nome);
    const local = semAspas(form.local);
    const fonte = form.origem === "webcam" ? form.indice.trim() || "0" : form.rtsp.trim();
    if (!nome) return setErro("Dê um nome para a câmera.");
    if (cameras.some((c) => c.nome.toLowerCase() === nome.toLowerCase())) {
      return setErro("Já existe uma câmera com esse nome. Use outro (ex.: “Quarto 2 - cama”).");
    }
    if (form.origem === "ip" && !/^(rtsp|https?):\/\//i.test(fonte)) {
      return setErro("O endereço da câmera IP começa com rtsp:// (ou http://). Veja no manual ou no app da câmera.");
    }

    if (form.computador === "novo") {
      const nomeComputador = form.nomeComputador.trim();
      if (!NOME_AGENTE_VALIDO.test(nomeComputador)) {
        return setErro("Nome do computador: só letras, números, espaço, ponto e hífen (até 80).");
      }
      try {
        const agente = await api.criarAgente(nomeComputador);
        aoCriarAgente?.();
        const env =
          `SENTINELA_URL=${window.location.origin}\nSENTINELA_TOKEN=${agente.token}\n` +
          `CAMERA_FONTE=${fonte}\nCAMERA_NOME=${nome}\nCAMERA_LOCAL=${local}\n`;
        setResultado({ nome, computador: agente.nome, env, comando: "python agente.py" });
      } catch (falha) {
        setErro(typeof falha.detalhe === "string" ? falha.detalhe : "Não foi possível criar a chave do computador.");
      }
    } else {
      // Computador que já tem agente: o .env dele já tem URL e chave; só abrimos mais uma câmera.
      const computador = computadores.find((c) => String(c.id) === form.computador);
      setResultado({
        nome,
        computador: computador?.nome,
        env: null,
        comando: `python agente.py --camera "${nome}" --local "${local}" --fonte "${fonte}"`,
      });
    }
  }

  async function copiar(texto, rotulo) {
    if (await copiarTexto(texto)) {
      setCopiado(rotulo);
      setTimeout(() => setCopiado(""), 2000);
    }
  }

  const conectada = resultado && estadoCameras.find((c) => c.nome === resultado.nome && c.online);

  return (
    <section className="cartao assistente">
      <header className="cartao__cabecalho assistente__cabecalho">
        <div>
          <h2>Adicionar câmera</h2>
          <p>{tipo === null ? "Escolha o tipo de câmera" : tipo === "aparelho" ? "Câmera deste aparelho" : "Câmera fixa ou IP"}</p>
        </div>
        <button type="button" className="botao-icone" onClick={aoFechar} aria-label="Fechar">
          <IconeFechar tamanho={16} />
        </button>
      </header>

      {tipo === null && (
        <div className="opcoes-camera">
          <button type="button" className="opcao-camera" onClick={() => setTipo("aparelho")}>
            <IconeCamera tamanho={22} />
            <strong>Este aparelho</strong>
            <span>Celular ou computador com a página aberta. Rápido para testar e para a apresentação.</span>
          </button>
          <button type="button" className="opcao-camera" onClick={() => setTipo("fixa")}>
            <IconeCamera tamanho={22} />
            <strong>Câmera fixa ou IP</strong>
            <span>Webcam ou câmera IP ligada a um computador com o agente. Para vigiar 24 horas.</span>
          </button>
        </div>
      )}

      {tipo === "aparelho" && cameraDoAparelho && <CameraDoAparelho camera={cameraDoAparelho} embutida />}

      {tipo === "fixa" && !resultado && (
        <form className="form-camera form-camera--grade" onSubmit={gerar}>
          <label>
            Nome da câmera
            <input required maxLength={80} placeholder="Ex.: Quarto 2" value={form.nome} onChange={mudar("nome")} />
          </label>
          <label>
            Local
            <input maxLength={60} placeholder="Ex.: 1º andar" value={form.local} onChange={mudar("local")} />
          </label>
          <label>
            De onde vem a imagem
            <select value={form.origem} onChange={mudar("origem")}>
              <option value="webcam">Webcam ligada no computador</option>
              <option value="ip">Câmera IP (endereço RTSP)</option>
            </select>
          </label>
          {form.origem === "webcam" ? (
            <label>
              Número da webcam
              <input inputMode="numeric" pattern="[0-9]{1,2}" value={form.indice} onChange={mudar("indice")} />
              <small>0 é a primeira; use 1, 2… se houver mais de uma.</small>
            </label>
          ) : (
            <label>
              Endereço RTSP
              <input placeholder="rtsp://usuario:senha@192.168.0.20:554/stream" value={form.rtsp} onChange={mudar("rtsp")} />
            </label>
          )}
          <label>
            Computador
            <select value={form.computador} onChange={mudar("computador")}>
              <option value="novo">Computador novo (gerar chave)</option>
              {computadores.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.nome} (já tem agente)
                </option>
              ))}
            </select>
          </label>
          {form.computador === "novo" && (
            <label>
              Nome do computador
              <input required maxLength={80} placeholder="Ex.: PC da recepção" value={form.nomeComputador} onChange={mudar("nomeComputador")} />
            </label>
          )}
          {erro && <p className="erro">{erro}</p>}
          <div className="linha-botoes">
            <button type="submit" className="botao">
              Gerar instruções
            </button>
            <button type="button" className="botao botao--fantasma" onClick={() => setTipo(null)}>
              Voltar
            </button>
          </div>
        </form>
      )}

      {tipo === "fixa" && resultado && (
        <div className="chave-nova">
          <strong>Pronto! Agora no computador “{resultado.computador}”:</strong>
          <ol className="passos-agente">
            {resultado.env && (
              <li>
                Na pasta do projeto, ponha estas linhas no arquivo <code>.env</code>.{" "}
                <b>A chave não será mostrada de novo</b>; não envie por chat nem e-mail.
                <pre className="bloco-codigo">{resultado.env}</pre>
                <button type="button" className="botao botao--pequeno" onClick={() => copiar(resultado.env, "env")}>
                  {copiado === "env" ? "Copiado!" : "Copiar .env"}
                </button>
              </li>
            )}
            <li>
              Abra um terminal na pasta do projeto e rode:
              <pre className="bloco-codigo">{resultado.comando}</pre>
              <button type="button" className="botao botao--pequeno" onClick={() => copiar(resultado.comando, "cmd")}>
                {copiado === "cmd" ? "Copiado!" : "Copiar comando"}
              </button>
            </li>
            <li>Deixe o terminal aberto. A câmera aparece na lista sozinha.</li>
          </ol>
          <p className={`espera-camera ${conectada ? "espera-camera--ok" : ""}`} role="status">
            <span className={`ponto ${conectada ? "ponto--on" : "ponto--off"}`} />
            {conectada ? `“${resultado.nome}” conectada!` : `Aguardando “${resultado.nome}” conectar…`}
          </p>
          <div className="linha-botoes">
            <button type="button" className="botao" onClick={aoFechar}>
              Concluir
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
