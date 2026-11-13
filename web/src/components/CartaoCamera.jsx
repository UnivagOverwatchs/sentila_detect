/*
 * CartaoCamera.jsx - Uma câmera na página "Câmeras": estado, edição e ações.
 *
 * LÓGICA
 *   - O selo de estado junta duas fontes: o cadastro (camera.ativa) e o tempo real (estado.online, vindo do WebSocket):
 *       desativada  -> o administrador desligou o monitoramento (interruptor);
 *       online      -> o agente ou o navegador mandou notícia há pouco;
 *       sem sinal   -> já conectou alguma vez, mas parou de mandar notícia;
 *       aguardando  -> cadastrada, mas nenhum agente conectou ainda.
 *   - "Editar" troca o texto por um formulário (nome e local) no próprio cartão, em vez de janelas do navegador.
 *   - "Área da cama" abre o EditorCama embaixo do cartão.
 */
import { useState } from "react";
import { EditorCama } from "./EditorCama.jsx";
import { haQuanto } from "./AgentesCamera.jsx";

/** Traduz cadastro + tempo real em { classe, texto } do selo. Exportada para os testes e para o resumo da página. */
export function situacaoDaCamera(camera, estado) {
  if (!camera.ativa) return { chave: "desativada", classe: "selo-camera--off", texto: "Desativada" };
  if (estado?.online === true) {
    return estado.deteccao === false
      ? { chave: "online", classe: "selo-camera--atencao", texto: "Online · só vídeo" }
      : { chave: "online", classe: "selo-camera--on", texto: "Online" };
  }
  if (estado?.online === false) return { chave: "sem-sinal", classe: "selo-camera--erro", texto: "Sem sinal" };
  return { chave: "aguardando", classe: "selo-camera--off", texto: "Aguardando conexão" };
}

export function CartaoCamera({ camera, estado, admin, aoSalvar, aoAlternar, aoExcluir, aoAtualizar }) {
  const [editando, setEditando] = useState(false);
  const [cama, setCama] = useState(false);
  const [dados, setDados] = useState({ nome: camera.nome, local: camera.local ?? "" });
  const [erro, setErro] = useState("");
  const situacao = situacaoDaCamera(camera, estado);
  const temCama = camera.area_cama?.length > 0;

  function abrirEdicao() {
    setDados({ nome: camera.nome, local: camera.local ?? "" });
    setErro("");
    setEditando(true);
  }

  async function salvar(e) {
    e.preventDefault();
    const nome = dados.nome.trim();
    if (!nome) return setErro("O nome é obrigatório.");
    try {
      await aoSalvar(camera, { nome, local: dados.local.trim() });
      setEditando(false);
    } catch (falha) {
      setErro(typeof falha?.detalhe === "string" ? falha.detalhe : "Não foi possível salvar. Tente de novo.");
    }
  }

  return (
    <li className="cartao-camera">
      <div className="cartao-camera__linha">
        {editando ? (
          <form className="form-camera" onSubmit={salvar}>
            <label>
              Nome
              <input autoFocus required maxLength={80} value={dados.nome} onChange={(e) => setDados({ ...dados, nome: e.target.value })} />
            </label>
            <label>
              Local
              <input maxLength={60} placeholder="Ex.: 1º andar" value={dados.local} onChange={(e) => setDados({ ...dados, local: e.target.value })} />
            </label>
            <div className="linha-botoes">
              <button className="botao botao--pequeno" type="submit">Salvar</button>
              <button className="botao botao--pequeno botao--fantasma" type="button" onClick={() => setEditando(false)}>
                Cancelar
              </button>
            </div>
            {erro && <p className="erro">{erro}</p>}
          </form>
        ) : (
          <div className="cartao-camera__info">
            <div className="cartao-camera__titulo">
              <strong>{camera.nome}</strong>
              <span className={`selo-camera ${situacao.classe}`}>{situacao.texto}</span>
            </div>
            <small>
              {camera.local || "Sem local"}
              {estado?.visto_ha_s != null && ` · último sinal ${haQuanto(estado.visto_ha_s)}`}
              {` · cama ${temCama ? "marcada" : "não marcada"}`}
            </small>
            {estado?.erro && <small className="erro">{estado.erro}</small>}
          </div>
        )}

        <label className="interruptor" title={camera.ativa ? "Monitorando: clique para desativar" : "Desativada: clique para ativar"}>
          <input type="checkbox" checked={camera.ativa} disabled={!admin} onChange={() => aoAlternar(camera)} />
          <span aria-hidden="true" />
          <span className="sr-only">Monitorar {camera.nome}</span>
        </label>
      </div>

      {admin && !editando && (
        <div className="cartao-camera__acoes">
          <button type="button" className="botao botao--pequeno botao--fantasma" onClick={abrirEdicao}>
            Editar
          </button>
          <button type="button" className="botao botao--pequeno botao--fantasma" onClick={() => setCama(!cama)} aria-expanded={cama}>
            {temCama ? "Área da cama" : "Marcar cama"}
          </button>
          <button type="button" className="botao botao--pequeno botao--perigo" onClick={() => aoExcluir(camera)}>
            Excluir
          </button>
        </div>
      )}

      {cama && <EditorCama camera={camera} aoSalvar={aoAtualizar} aoFechar={() => setCama(false)} />}
    </li>
  );
}
