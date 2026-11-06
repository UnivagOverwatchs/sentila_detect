/*
 * Configuracoes.jsx - Configurações (Figura 12; UC09, RF11).
 *   - Sensibilidade de detecção (um controle que ajusta todos os limiares no servidor).
 *   - Câmeras cadastradas: ligar/desligar o monitoramento.
 *   - Contatos de emergência: usados no botão "Ligar" da tela de alerta.
 *   - Este aparelho: nome do cuidador e permissão de notificações.
 *   - Aparelhos que recebem alertas: lista dos celulares cadastrados para o push (renomear/remover).
 */
import { useEffect, useState } from "react";
import { IconeFechar, IconeMais, IconeSino, IconeTelefone } from "../components/Icones.jsx";
import { api } from "../services/api.js";
import { pedirPermissaoNotificacao } from "../services/aviso.js";
import { ativarPush, pushDisponivel } from "../services/push.js";

function rotuloNivel(valor) {
  const pct = Math.round(valor * 100);
  return pct < 34 ? "Baixa" : pct < 60 ? "Média" : "Alta";
}

export function Configuracoes({
  sensibilidade,
  aoSalvarSensibilidade,
  cameras,
  aoAlternarCamera,
  contatos,
  aoCriarContato,
  aoRemoverContato,
  nomeCuidador,
  aoSalvarNome,
}) {
  const [valor, setValor] = useState(sensibilidade ?? 0.65);
  const [novo, setNovo] = useState({ nome: "", telefone: "", tipo: "Familiar" });
  const [formAberto, setFormAberto] = useState(false);
  const [erroContato, setErroContato] = useState("");
  const [pushEstado, setPushEstado] = useState("");
  const [aparelhos, setAparelhos] = useState([]);

  async function carregarAparelhos() {
    try {
      setAparelhos(await api.aparelhos());
    } catch {
      /* sem rede: mantém a lista anterior */
    }
  }

  useEffect(() => {
    carregarAparelhos();
  }, [pushEstado]);

  async function renomear(aparelho) {
    const nome = window.prompt("Nome do aparelho", aparelho.nome ?? "");
    if (nome && nome.trim()) {
      await api.renomearAparelho(aparelho.id, nome.trim());
      carregarAparelhos();
    }
  }

  async function removerAparelho(aparelho) {
    if (window.confirm(`Remover "${aparelho.nome ?? "aparelho"}"? Ele deixa de receber alertas.`)) {
      await api.removerAparelho(aparelho.id);
      carregarAparelhos();
    }
  }
  const [permissao, setPermissao] = useState("Notification" in window ? Notification.permission : "indisponivel");

  useEffect(() => {
    if (sensibilidade != null) setValor(sensibilidade);
  }, [sensibilidade]);

  async function adicionarContato(e) {
    e.preventDefault();
    setErroContato("");
    try {
      await aoCriarContato(novo);
      setNovo({ nome: "", telefone: "", tipo: "Familiar" });
      setFormAberto(false);
    } catch {
      setErroContato("Confira o telefone: use apenas números, espaços, +, ( ) e -.");
    }
  }

  return (
    <div className="pilha">
      <section className="cartao">
        <header className="cartao__cabecalho">
          <h2>Sensibilidade de detecção</h2>
          <p>Ajuste o quão sensível o sistema é para gerar um alerta de queda</p>
        </header>
        <input
          className="controle-deslizante"
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={valor}
          style={{ "--preenchido": `${valor * 100}%` }}
          onChange={(e) => setValor(Number(e.target.value))}
          // Salva só ao soltar o controle, para não enviar dezenas de requisições.
          onMouseUp={() => aoSalvarSensibilidade(valor)}
          onTouchEnd={() => aoSalvarSensibilidade(valor)}
          onKeyUp={() => aoSalvarSensibilidade(valor)}
          aria-label="Sensibilidade de detecção"
        />
        <div className="deslizante-legenda">
          <span>Menos alertas</span>
          <strong>
            {rotuloNivel(valor)} ({Math.round(valor * 100)}%)
          </strong>
          <span>Mais alertas</span>
        </div>
      </section>

      <section className="cartao">
        <header className="cartao__cabecalho">
          <h2>Câmeras cadastradas</h2>
        </header>
        <ul className="lista-config">
          {cameras.map((c) => (
            <li key={c.id}>
              <div>
                <strong>{c.nome}</strong>
                <small>{c.local}</small>
              </div>
              <label className="interruptor">
                <input type="checkbox" checked={c.ativa} onChange={() => aoAlternarCamera(c)} />
                <span aria-hidden="true" />
                <span className="sr-only">Monitorar {c.nome}</span>
              </label>
            </li>
          ))}
        </ul>
        <p className="dica">
          Para adicionar outra câmera, inicie o servidor com <code>--fonte</code> e <code>--camera</code>.
        </p>
      </section>

      <section className="cartao">
        <header className="cartao__cabecalho">
          <h2>Contatos de emergência</h2>
        </header>
        <ul className="lista-config">
          {contatos.map((c) => (
            <li key={c.id}>
              <span className="avatar avatar--claro">
                <IconeTelefone tamanho={14} />
              </span>
              <div className="lista-config__expande">
                <strong>{c.nome}</strong>
                <small className="mono">
                  {c.telefone} · {c.tipo}
                </small>
              </div>
              <button className="botao-icone" onClick={() => aoRemoverContato(c)} aria-label={`Remover ${c.nome}`}>
                <IconeFechar tamanho={14} />
              </button>
            </li>
          ))}
        </ul>
        {formAberto ? (
          <form className="form-contato" onSubmit={adicionarContato}>
            <input required placeholder="Nome" value={novo.nome} onChange={(e) => setNovo({ ...novo, nome: e.target.value })} />
            <input
              required
              placeholder="Telefone"
              inputMode="tel"
              value={novo.telefone}
              onChange={(e) => setNovo({ ...novo, telefone: e.target.value })}
            />
            <select value={novo.tipo} onChange={(e) => setNovo({ ...novo, tipo: e.target.value })}>
              <option>Familiar</option>
              <option>Emergência</option>
              <option>Equipe</option>
            </select>
            <button className="botao" type="submit">Salvar</button>
            <button className="botao botao--fantasma" type="button" onClick={() => setFormAberto(false)}>
              Cancelar
            </button>
            {erroContato && <p className="erro">{erroContato}</p>}
          </form>
        ) : (
          <button className="botao-tracejado" onClick={() => setFormAberto(true)}>
            <IconeMais tamanho={14} /> Adicionar contato
          </button>
        )}
      </section>

      <section className="cartao">
        <header className="cartao__cabecalho">
          <h2>Este aparelho</h2>
          <p>Seu nome fica registrado quando você trata um alerta</p>
        </header>
        <div className="linha-form">
          <input
            defaultValue={nomeCuidador}
            onBlur={(e) => aoSalvarNome(e.target.value.trim() || "Cuidador")}
            aria-label="Seu nome"
          />
          <button
            className="botao botao--fantasma"
            disabled={permissao === "indisponivel"}
            onClick={async () => {
              setPermissao(await pedirPermissaoNotificacao());
              if (pushDisponivel()) setPushEstado(await ativarPush());
            }}
          >
            <IconeSino tamanho={14} />
            {permissao === "granted" ? "Notificações ativas" : "Ativar notificações"}
          </button>
        </div>
        {pushEstado === "erro" && (
          <p className="erro">Não foi possível ativar o aviso com o app fechado (precisa de HTTPS e do push configurado no servidor).</p>
        )}
        {pushEstado === "ativo" && <p className="dica">Pronto: este aparelho também recebe alertas com o app fechado.</p>}
      </section>

      <section className="cartao">
        <header className="cartao__cabecalho">
          <h2>Aparelhos que recebem alertas</h2>
          <p>Celulares cadastrados para o aviso com o app fechado</p>
        </header>
        {aparelhos.length === 0 ? (
          <p className="dica">Nenhum aparelho cadastrado ainda. Toque em &quot;Ativar notificações&quot; no celular.</p>
        ) : (
          <ul className="lista-config">
            {aparelhos.map((a) => (
              <li key={a.id}>
                <span className="avatar avatar--claro">
                  <IconeSino tamanho={14} />
                </span>
                <div className="lista-config__expande">
                  <strong>{a.nome ?? "Aparelho"}</strong>
                  <small className="mono">
                    {a.ultimo_resultado
                      ? `Último aviso: ${a.ultimo_resultado === "OK" ? "enviado" : "falhou"} · ${String(a.ultimo_envio).replace("T", " ").slice(0, 16)}`
                      : "Nenhum aviso enviado ainda"}
                  </small>
                </div>
                <button className="botao botao--fantasma" onClick={() => renomear(a)}>
                  Renomear
                </button>
                <button className="botao-icone" onClick={() => removerAparelho(a)} aria-label={`Remover ${a.nome ?? "aparelho"}`}>
                  <IconeFechar tamanho={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
