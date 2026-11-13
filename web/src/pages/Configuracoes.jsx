/*
 * Configuracoes.jsx - Configurações (Figura 12; UC09, RF11).
 *   - Sensibilidade de detecção (um controle que ajusta todos os limiares no servidor).
 *   (Câmeras e computadores com agente ficam na página "Câmeras", em pages/Cameras.jsx.)
 *   - Contatos de emergência: usados no botão "Ligar" da tela de alerta.
 *   - Este aparelho: nome do cuidador e permissão de notificações.
 *   - Usuários (só administrador): criar, ativar/desativar e trocar a senha.
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
  contatos,
  aoCriarContato,
  aoRemoverContato,
  nomeCuidador,
  aoSalvarNome,
  admin = true,
  usuarioLogado = null,
}) {
  const [valor, setValor] = useState(sensibilidade ?? 0.65);
  const [novo, setNovo] = useState({ nome: "", telefone: "", tipo: "Familiar" });
  const [formAberto, setFormAberto] = useState(false);
  const [erroContato, setErroContato] = useState("");
  const [pushEstado, setPushEstado] = useState("");
  const [aparelhos, setAparelhos] = useState([]);

  async function carregarAparelhos() {
    if (!admin) return;
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
          disabled={!admin}
        />
        <div className="deslizante-legenda">
          <span>Menos alertas</span>
          <strong>
            {rotuloNivel(valor)} ({Math.round(valor * 100)}%)
          </strong>
          <span>Mais alertas</span>
        </div>
      </section>

      <p className="dica">
        Câmeras e computadores com agente agora ficam na aba <a href="#/cameras">Câmeras</a>.
      </p>


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
              {admin && (
                <button className="botao-icone" onClick={() => aoRemoverContato(c)} aria-label={`Remover ${c.nome}`}>
                  <IconeFechar tamanho={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
        {!admin ? null : formAberto ? (
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

      {admin && <SecaoUsuarios usuarioLogado={usuarioLogado} />}

      {admin && (
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
      )}
    </div>
  );
}

/** Administração de usuários (só aparece para ADMIN, ou quando o servidor não exige login). */
function SecaoUsuarios({ usuarioLogado }) {
  const [usuarios, setUsuarios] = useState([]);
  const [aberto, setAberto] = useState(false);
  const [novo, setNovo] = useState({ usuario: "", nome: "", senha: "", papel: "CUIDADOR" });
  const [erro, setErro] = useState("");

  async function carregar() {
    try {
      setUsuarios(await api.usuarios());
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
      await api.criarUsuario({ ...novo, usuario: novo.usuario.trim().toLowerCase(), nome: novo.nome.trim() });
      setNovo({ usuario: "", nome: "", senha: "", papel: "CUIDADOR" });
      setAberto(false);
      carregar();
    } catch (falha) {
      setErro(typeof falha.detalhe === "string" ? falha.detalhe : "Confira os campos: login com letras minúsculas, números, ponto, hífen ou sublinhado (3 a 60) e senha de 10+ caracteres.");
    }
  }

  async function alternarAtivo(u) {
    try {
      await api.atualizarUsuario(u.id, { ativo: !u.ativo });
      carregar();
    } catch (falha) {
      window.alert(typeof falha.detalhe === "string" ? falha.detalhe : "Não foi possível alterar.");
    }
  }

  async function trocarSenha(u) {
    const senha = window.prompt(`Nova senha para ${u.nome} (mínimo 10 caracteres)`);
    if (!senha) return;
    try {
      await api.atualizarUsuario(u.id, { senha });
      window.alert("Senha alterada. As sessões abertas desse usuário foram encerradas.");
    } catch (falha) {
      window.alert(typeof falha.detalhe === "string" ? falha.detalhe : "Não foi possível trocar a senha.");
    }
  }

  return (
    <section className="cartao">
      <header className="cartao__cabecalho">
        <h2>Usuários</h2>
        <p>Quem pode entrar no painel. Administrador altera tudo; cuidador acompanha e trata alertas.</p>
      </header>
      <ul className="lista-config">
        {usuarios.map((u) => (
          <li key={u.id}>
            <span className="avatar avatar--claro">{u.nome.charAt(0).toUpperCase()}</span>
            <div className="lista-config__expande">
              <strong>
                {u.nome}
                {usuarioLogado?.usuario === u.usuario ? " (você)" : ""}
              </strong>
              <small className="mono">
                {u.usuario} · {u.papel === "ADMIN" ? "Administrador" : "Cuidador"} · {u.ativo ? "ativo" : "desativado"}
              </small>
            </div>
            <button className="botao botao--fantasma" onClick={() => trocarSenha(u)}>
              Senha
            </button>
            {usuarioLogado?.usuario !== u.usuario && (
              <button className="botao botao--fantasma" onClick={() => alternarAtivo(u)}>
                {u.ativo ? "Desativar" : "Ativar"}
              </button>
            )}
          </li>
        ))}
      </ul>
      {aberto ? (
        <form className="form-usuario" onSubmit={criar}>
          <input required placeholder="Login (ex.: maria)" autoCapitalize="none" value={novo.usuario} onChange={(e) => setNovo({ ...novo, usuario: e.target.value })} />
          <input required placeholder="Nome" value={novo.nome} onChange={(e) => setNovo({ ...novo, nome: e.target.value })} />
          <input required type="password" autoComplete="new-password" placeholder="Senha (10+ caracteres)" value={novo.senha} onChange={(e) => setNovo({ ...novo, senha: e.target.value })} />
          <select value={novo.papel} onChange={(e) => setNovo({ ...novo, papel: e.target.value })}>
            <option value="CUIDADOR">Cuidador</option>
            <option value="ADMIN">Administrador</option>
          </select>
          <button className="botao" type="submit">Criar</button>
          <button className="botao botao--fantasma" type="button" onClick={() => setAberto(false)}>Cancelar</button>
          {erro && <p className="erro">{erro}</p>}
        </form>
      ) : (
        <button className="botao-tracejado" onClick={() => setAberto(true)}>
          <IconeMais tamanho={14} /> Adicionar usuário
        </button>
      )}
    </section>
  );
}
