/*
 * Layout.jsx - Estrutura comum às telas (igual ao protótipo da documentação):
 *   - Desktop: barra lateral escura com navegação, câmeras monitoradas e o cuidador.
 *   - Celular: a barra lateral some e aparece a navegação inferior (Figura 13).
 *   - Topo: título da tela + selo de estado geral (Normal / Atenção / Alerta).
 */
import { IconeAjustes, IconeCasa, IconeEscudo, IconeRelogio } from "./Icones.jsx";

const PAGINAS = [
  { id: "painel", rotulo: "Painel", Icone: IconeCasa },
  { id: "historico", rotulo: "Histórico", Icone: IconeRelogio },
  { id: "config", rotulo: "Configurações", rotuloCurto: "Config", Icone: IconeAjustes },
];

const SELO = {
  normal: { classe: "selo--normal", texto: "Normal" },
  atencao: { classe: "selo--atencao", texto: "Atenção" },
  alerta: { classe: "selo--alerta", texto: "Alerta" },
  offline: { classe: "selo--offline", texto: "Sem conexão" },
  camera: { classe: "selo--atencao", texto: "Câmera offline" },
};

export function Layout({ pagina, irPara, titulo, subtitulo, estado, cameras, nomeCuidador, rotuloPapel = "Cuidador responsável", aoSair, children }) {
  const selo = SELO[estado] ?? SELO.normal;
  return (
    <div className="app">
      <aside className="lateral">
        <div className="marca">
          <IconeEscudo tamanho={20} />
          <span>Sentinela</span>
        </div>

        <nav className="lateral__nav" aria-label="Navegação principal">
          {PAGINAS.map(({ id, rotulo, Icone }) => (
            <button
              key={id}
              className={`lateral__item ${pagina === id ? "ativo" : ""}`}
              onClick={() => irPara(id)}
              aria-current={pagina === id ? "page" : undefined}
            >
              <Icone tamanho={16} />
              {rotulo}
            </button>
          ))}
        </nav>

        <p className="lateral__secao">Câmeras monitoradas</p>
        <ul className="lateral__cameras">
          {cameras.map((c) => (
            <li key={c.id}>
              <span className={`ponto ${c.ativa ? "ponto--on" : "ponto--off"}`} />
              {c.nome}
            </li>
          ))}
        </ul>

        <div className="lateral__usuario">
          <span className="avatar">{nomeCuidador.charAt(0).toUpperCase()}</span>
          <div>
            <strong>{nomeCuidador}</strong>
            <small>{rotuloPapel}</small>
          </div>
          {aoSair && (
            <button className="botao botao--fantasma lateral__sair" onClick={aoSair}>
              Sair
            </button>
          )}
        </div>
      </aside>

      <div className="conteudo">
        <header className="topo">
          <div className="topo__marca-mobile">
            <IconeEscudo tamanho={18} />
            <span>Sentinela</span>
          </div>
          <div className="topo__titulos">
            <h1>{titulo}</h1>
            <p>{subtitulo}</p>
          </div>
          <span className={`selo ${selo.classe}`} role="status">
            <IconeEscudo tamanho={14} />
            {selo.texto}
          </span>
        </header>
        <main className="pagina">{children}</main>
      </div>

      <nav className="nav-inferior" aria-label="Navegação">
        {PAGINAS.map(({ id, rotulo, rotuloCurto, Icone }) => (
          <button key={id} className={pagina === id ? "ativo" : ""} onClick={() => irPara(id)}>
            <Icone tamanho={20} />
            <span>{rotuloCurto ?? rotulo}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
