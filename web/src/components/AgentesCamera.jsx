/*
 * AgentesCamera.jsx - Adicionar câmera e gerenciar as chaves dos agentes (só administrador).
 *
 * Um AGENTE é o programa (agente.py) que roda onde a câmera é alcançável e envia alertas, fotos e vídeo ao painel.
 * Cada agente tem uma chave. Aqui o administrador cria a chave, copia o comando pronto e, se precisar,
 * troca a chave ou revoga o acesso, sem entrar na VPS.
 *
 * A chave aparece UMA vez (o servidor guarda só o hash). Se for perdida, gere outra com "Nova chave".
 */
import { useEffect, useState } from "react";
import { IconeMais } from "./Icones.jsx";
import { api } from "../services/api.js";

function haQuanto(segundos) {
  if (segundos == null) return "nunca";
  if (segundos < 90) return "agora há pouco";
  if (segundos < 3600) return `há ${Math.round(segundos / 60)} min`;
  if (segundos < 86400) return `há ${Math.round(segundos / 3600)} h`;
  return `há ${Math.round(segundos / 86400)} dias`;
}

export function AgentesCamera() {
  const [agentes, setAgentes] = useState([]);
  const [nome, setNome] = useState("");
  const [aberto, setAberto] = useState(false);
  const [erro, setErro] = useState("");
  const [chave, setChave] = useState(null); // { nome, token }: mostrada uma única vez
  const [copiado, setCopiado] = useState("");

  async function carregar() {
    try {
      setAgentes(await api.agentes());
    } catch {
      /* sem permissão ou sem rede */
    }
  }

  useEffect(() => {
    carregar();
  }, []);

  async function criar(e) {
    e.preventDefault();
    setErro("");
    try {
      const novo = await api.criarAgente(nome.trim());
      setChave({ nome: novo.nome, token: novo.token });
      setNome("");
      setAberto(false);
      carregar();
    } catch (falha) {
      setErro(typeof falha.detalhe === "string" ? falha.detalhe : "Use só letras, números, espaço, ponto e hífen (até 80).");
    }
  }

  async function novaChave(agente) {
    if (!window.confirm(`Gerar uma nova chave para "${agente.nome}"? A chave atual deixa de funcionar na hora.`)) return;
    try {
      const r = await api.novaChaveAgente(agente.id);
      setChave({ nome: r.nome, token: r.token });
      carregar();
    } catch (falha) {
      window.alert(typeof falha.detalhe === "string" ? falha.detalhe : "Não foi possível gerar a chave.");
    }
  }

  async function alternar(agente) {
    const acao = agente.ativo ? "Revogar o acesso de" : "Reativar";
    if (!window.confirm(`${acao} "${agente.nome}"?`)) return;
    await api.atualizarAgente(agente.id, !agente.ativo);
    carregar();
  }

  async function copiar(texto, rotulo) {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(rotulo);
      setTimeout(() => setCopiado(""), 2000);
    } catch {
      window.alert("Não consegui copiar sozinho. Selecione o texto e copie com Ctrl+C.");
    }
  }

  const envTexto = chave
    ? `SENTINELA_URL=${window.location.origin}\nSENTINELA_TOKEN=${chave.token}\nCAMERA_FONTE=0\nCAMERA_NOME=Sala\nCAMERA_LOCAL=Térreo\n`
    : "";

  return (
    <section className="cartao">
      <header className="cartao__cabecalho">
        <h2>Agentes de câmera</h2>
        <p>
          Cada câmera é ligada por um agente (<code>agente.py</code>) que roda onde ela é alcançável. Crie uma chave para
          cada computador.
        </p>
      </header>

      {chave && (
        <div className="chave-nova" role="alert">
          <strong>Chave do agente “{chave.nome}”</strong>
          <p className="aviso-chave">
            Copie agora: <b>ela não será mostrada de novo</b>. Não envie por chat nem e-mail.
          </p>
          <pre className="bloco-codigo">{envTexto}</pre>
          <div className="linha-botoes">
            <button type="button" className="botao botao--pequeno" onClick={() => copiar(envTexto, "env")}>
              {copiado === "env" ? "Copiado!" : "Copiar linhas do .env"}
            </button>
            <button type="button" className="botao botao--pequeno botao--fantasma" onClick={() => copiar(chave.token, "chave")}>
              {copiado === "chave" ? "Copiado!" : "Copiar só a chave"}
            </button>
            <button type="button" className="botao botao--pequeno botao--fantasma" onClick={() => setChave(null)}>
              Já copiei, fechar
            </button>
          </div>
          <ol className="passos-agente">
            <li>No computador da câmera, ponha as linhas acima no arquivo <code>.env</code> da pasta do projeto.</li>
            <li>
              Troque <code>CAMERA_FONTE</code>: <code>0</code> é a webcam; para câmera IP use{" "}
              <code>rtsp://usuario:senha@IP:554/caminho</code>.
            </li>
            <li>
              Rode: <code>python agente.py --camera "Sala" --local "Térreo"</code>
            </li>
            <li>A câmera aparece no Painel em poucos segundos. Para outra câmera no mesmo computador, use outro terminal e outro nome.</li>
          </ol>
        </div>
      )}

      <ul className="lista-config">
        {agentes.map((a) => (
          <li key={a.id}>
            <div className="lista-config__expande">
              <strong>{a.nome}</strong>
              <small className="mono">
                {a.ativo ? "ativo" : "REVOGADO"} · último contato: {haQuanto(a.ultimo_contato_ha_s)}
              </small>
            </div>
            <button className="botao botao--fantasma" onClick={() => novaChave(a)}>
              Nova chave
            </button>
            <button className="botao botao--fantasma" onClick={() => alternar(a)}>
              {a.ativo ? "Revogar" : "Reativar"}
            </button>
          </li>
        ))}
        {agentes.length === 0 && <li className="dica">Nenhum agente ainda. Adicione o primeiro abaixo.</li>}
      </ul>

      {aberto ? (
        <form className="form-usuario" onSubmit={criar}>
          <input
            required
            placeholder="Nome do computador (ex.: Casa da Anni)"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            maxLength={80}
          />
          <button className="botao" type="submit">
            Criar chave
          </button>
          <button className="botao botao--fantasma" type="button" onClick={() => setAberto(false)}>
            Cancelar
          </button>
          {erro && <p className="erro">{erro}</p>}
        </form>
      ) : (
        <button className="botao-tracejado" onClick={() => setAberto(true)}>
          <IconeMais tamanho={14} /> Adicionar câmera (novo agente)
        </button>
      )}
    </section>
  );
}
