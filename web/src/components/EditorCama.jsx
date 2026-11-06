/*
 * EditorCama.jsx - Marcar na imagem da câmera onde fica a cama.
 *
 * Deitar DENTRO da área marcada é normal e não gera alerta de queda; fora dela tudo continua igual.
 * O administrador clica nos cantos da cama (3 a 12 pontos por zona, até 4 zonas). As coordenadas
 * são salvas como fração da imagem (0 a 1), então valem em qualquer tamanho de tela.
 */
import { useEffect, useState } from "react";
import { api } from "../services/api.js";

const MAX_ZONAS = 4;
const MAX_PONTOS = 12;

const pontosSvg = (poli) => poli.map(([x, y]) => `${x * 100},${y * 100}`).join(" ");

export function EditorCama({ camera, aoSalvar, aoFechar }) {
  const [zonas, setZonas] = useState(camera.area_cama ?? []);
  const [atual, setAtual] = useState([]); // zona que está sendo desenhada
  const [quadro, setQuadro] = useState(null);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");

  // Um quadro parado serve de fundo: desenhar sobre vídeo em movimento seria difícil.
  useEffect(() => {
    let url;
    let ativo = true;
    fetch(api.urlQuadro(), { cache: "no-store", credentials: "same-origin" })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((blob) => {
        url = URL.createObjectURL(blob);
        if (ativo) setQuadro(url);
      })
      .catch(() => ativo && setErro("Não consegui carregar a imagem da câmera."));
    return () => {
      ativo = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, []);

  function clicar(evento) {
    if (atual.length >= MAX_PONTOS) return;
    const caixa = evento.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (evento.clientX - caixa.left) / caixa.width));
    const y = Math.min(1, Math.max(0, (evento.clientY - caixa.top) / caixa.height));
    setAtual([...atual, [Number(x.toFixed(4)), Number(y.toFixed(4))]]);
  }

  function concluirZona() {
    if (atual.length < 3 || zonas.length >= MAX_ZONAS) return;
    setZonas([...zonas, atual]);
    setAtual([]);
  }

  function desfazer() {
    if (atual.length) setAtual(atual.slice(0, -1));
    else setZonas(zonas.slice(0, -1));
  }

  function limpar() {
    setZonas([]);
    setAtual([]);
  }

  async function salvar() {
    const final = atual.length >= 3 && zonas.length < MAX_ZONAS ? [...zonas, atual] : zonas;
    setSalvando(true);
    setErro("");
    try {
      const atualizada = await api.salvarAreaCama(camera.id, final);
      aoSalvar(atualizada);
      aoFechar();
    } catch (e) {
      setErro(e.detalhe ? "Dados inválidos para a área da cama." : "Não foi possível salvar. Tente de novo.");
    } finally {
      setSalvando(false);
    }
  }

  const vazio = !atual.length && !zonas.length;

  return (
    <div className="editor-cama">
      <p className="dica">
        Clique nos cantos da cama, na ordem. Com 3 ou mais pontos, toque em <strong>Concluir cama</strong>. Deitar dentro da
        área marcada não gera alerta.
      </p>
      <div className="editor-cama__imagem" onClick={clicar} role="presentation">
        {quadro ? (
          <img src={quadro} alt={`Imagem da câmera ${camera.nome}`} draggable={false} />
        ) : (
          <span>Carregando imagem…</span>
        )}
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {zonas.map((z, i) => (
            <polygon key={i} points={pontosSvg(z)} className="editor-cama__zona" />
          ))}
          {atual.length >= 2 && <polyline points={pontosSvg(atual)} className="editor-cama__tracado" />}
          {atual.map(([x, y], i) => (
            <circle key={i} cx={x * 100} cy={y * 100} r="1" className="editor-cama__ponto" />
          ))}
        </svg>
      </div>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      <div className="editor-cama__acoes">
        <button
          type="button"
          className="botao botao--pequeno"
          onClick={concluirZona}
          disabled={atual.length < 3 || zonas.length >= MAX_ZONAS}
        >
          Concluir cama
        </button>
        <button type="button" className="botao botao--pequeno botao--fantasma" onClick={desfazer} disabled={vazio}>
          Desfazer
        </button>
        <button type="button" className="botao botao--pequeno botao--fantasma" onClick={limpar} disabled={vazio}>
          Limpar tudo
        </button>
        <span className="editor-cama__espaco" />
        <button type="button" className="botao botao--pequeno botao--fantasma" onClick={aoFechar}>
          Cancelar
        </button>
        <button type="button" className="botao botao--pequeno" onClick={salvar} disabled={salvando}>
          {salvando ? "Salvando…" : "Salvar"}
        </button>
      </div>
    </div>
  );
}
