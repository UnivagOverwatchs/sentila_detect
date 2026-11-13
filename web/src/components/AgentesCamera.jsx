/*
 * AgentesCamera.jsx - Computadores com agente (só administrador).
 *
 * Um AGENTE é o programa (agente.py) que roda no computador que alcança a câmera e envia alertas, fotos e vídeo ao painel.
 * Cada computador tem uma chave. Criar a chave agora é feito no assistente "Adicionar câmera" (AdicionarCamera.jsx);
 * aqui ficam só as ações do dia a dia: ver quem está conectado, trocar a chave e revogar o acesso.
 *
 * A chave aparece UMA vez (o servidor guarda só o hash). Se for perdida, gere outra com "Nova chave".
 *
 * Exporta também:
 *   - haQuanto(segundos): texto "há 5 min" usado nos cartões de câmera;
 *   - copiarTexto(texto): copia para a área de transferência com aviso se o navegador bloquear.
 */
import { useEffect, useState } from "react";
import { api } from "../services/api.js";

export function haQuanto(segundos) {
  if (segundos == null) return "nunca";
  if (segundos < 90) return "agora há pouco";
  if (segundos < 3600) return `há ${Math.round(segundos / 60)} min`;
  if (segundos < 86400) return `há ${Math.round(segundos / 3600)} h`;
  return `há ${Math.round(segundos / 86400)} dias`;
}

export async function copiarTexto(texto) {
  try {
    await navigator.clipboard.writeText(texto);
    return true;
  } catch {
    window.alert("Não consegui copiar sozinho. Selecione o texto e copie com Ctrl+C.");
    return false;
  }
}

/** Agentes criados pela câmera do navegador ("Navegador [...]") não são computadores: ficam fora desta lista. */
const ehNavegador = (agente) => agente.nome.startsWith("Navegador [");

export function AgentesCamera({ versao = 0 }) {
  const [agentes, setAgentes] = useState([]);
  const [chave, setChave] = useState(null); // { nome, token }: mostrada uma única vez
  const [copiado, setCopiado] = useState(false);

  async function carregar() {
    try {
      setAgentes((await api.agentes()).filter((a) => !ehNavegador(a)));
    } catch {
      /* sem permissão ou sem rede */
    }
  }

  // "versao" muda quando o assistente cria um agente novo: recarrega a lista.
  useEffect(() => {
    carregar();
  }, [versao]);

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
    const acao = agente.ativo
      ? `Revogar o acesso de "${agente.nome}"? As câmeras dele param de enviar alertas até você reativar.`
      : `Reativar "${agente.nome}"?`;
    if (!window.confirm(acao)) return;
    await api.atualizarAgente(agente.id, !agente.ativo);
    carregar();
  }

  return (
    <section className="cartao">
      <header className="cartao__cabecalho">
        <h2>Computadores com agente</h2>
        <p>Computadores que rodam o <code>agente.py</code> e enviam as câmeras fixas ou IP para o painel.</p>
      </header>

      {chave && (
        <div className="chave-nova" role="alert">
          <strong>Nova chave de “{chave.nome}”</strong>
          <p className="aviso-chave">
            Copie agora: <b>ela não será mostrada de novo</b>. Troque o <code>SENTINELA_TOKEN</code> no <code>.env</code> desse
            computador e reinicie o agente.
          </p>
          <pre className="bloco-codigo">{`SENTINELA_TOKEN=${chave.token}`}</pre>
          <div className="linha-botoes">
            <button
              type="button"
              className="botao botao--pequeno"
              onClick={async () => setCopiado(await copiarTexto(`SENTINELA_TOKEN=${chave.token}`))}
            >
              {copiado ? "Copiado!" : "Copiar"}
            </button>
            <button type="button" className="botao botao--pequeno botao--fantasma" onClick={() => setChave(null)}>
              Já copiei, fechar
            </button>
          </div>
        </div>
      )}

      <ul className="lista-config">
        {agentes.map((a) => (
          <li key={a.id}>
            <span className={`ponto ${a.ativo && a.ultimo_contato_ha_s != null && a.ultimo_contato_ha_s < 120 ? "ponto--on" : "ponto--off"}`} />
            <div className="lista-config__expande">
              <strong>{a.nome}</strong>
              <small className="mono">
                {a.ativo ? "ativo" : "REVOGADO"} · último contato: {haQuanto(a.ultimo_contato_ha_s)}
              </small>
            </div>
            <button className="botao botao--pequeno botao--fantasma" onClick={() => novaChave(a)}>
              Nova chave
            </button>
            <button className="botao botao--pequeno botao--fantasma" onClick={() => alternar(a)}>
              {a.ativo ? "Revogar" : "Reativar"}
            </button>
          </li>
        ))}
        {agentes.length === 0 && (
          <li className="dica">Nenhum computador ainda. Use “Adicionar câmera” → “Câmera fixa ou IP”.</li>
        )}
      </ul>
    </section>
  );
}
