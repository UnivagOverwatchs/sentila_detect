/*
 * Historico.jsx - Histórico de alertas (Figura 11; RF09).
 * Filtro por tipo, foto do momento e ações "Resolver" / "Falso alarme".
 * Os falsos alarmes ficam registrados: servem para calibrar a sensibilidade (Figura 7).
 */
import { useState } from "react";
import { api } from "../services/api.js";
import { dia, hora, ROTULO_STATUS, ROTULO_TIPO } from "../services/formato.js";
import { IconeImagem } from "../components/Icones.jsx";

const FILTROS = [
  { id: "", rotulo: "Todos" },
  { id: "QUEDA", rotulo: "Quedas" },
  { id: "MOVIMENTO_ANOMALO", rotulo: "Pessoa no chão" },
];

export function Historico({ alertas, aoTratar, offline }) {
  const [filtro, setFiltro] = useState("");
  const visiveis = filtro ? alertas.filter((a) => a.tipo === filtro) : alertas;

  return (
    <section className="cartao">
      <div className="filtros" role="tablist" aria-label="Filtrar por tipo">
        {FILTROS.map((f) => (
          <button
            key={f.id}
            role="tab"
            aria-selected={filtro === f.id}
            className={`chip ${filtro === f.id ? "ativo" : ""}`}
            onClick={() => setFiltro(f.id)}
          >
            {f.rotulo}
          </button>
        ))}
        {offline && <span className="aviso-offline">Sem conexão — exibindo últimos alertas salvos</span>}
      </div>

      {visiveis.length === 0 ? (
        <div className="vazio">Nenhum alerta para este filtro.</div>
      ) : (
        <div className="tabela-rolagem">
          <table className="tabela">
            <thead>
              <tr>
                <th>Horário</th>
                <th>Câmera</th>
                <th>Tipo</th>
                <th>Foto</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {visiveis.map((a) => (
                <tr key={a.id}>
                  <td className="mono">
                    {hora(a.ocorrido_em)}
                    <small>{dia(a.ocorrido_em)}</small>
                  </td>
                  <td>{a.camera_nome}</td>
                  <td>
                    <span className={`etiqueta etiqueta--${a.tipo === "QUEDA" ? "queda" : "chao"}`}>
                      {ROTULO_TIPO[a.tipo]}
                    </span>
                  </td>
                  <td>
                    {a.imagem ? (
                      <a className="link-foto" href={api.urlImagemAlerta(a.id)} target="_blank" rel="noreferrer">
                        <IconeImagem tamanho={14} /> Ver
                      </a>
                    ) : (
                      <span className="texto-fraco">—</span>
                    )}
                  </td>
                  <td>
                    {a.status === "PENDENTE" ? (
                      <div className="acoes">
                        <button className="botao botao--pequeno" disabled={offline} onClick={() => aoTratar(a, "RESOLVIDO")}>
                          Resolver
                        </button>
                        <button
                          className="botao botao--pequeno botao--fantasma"
                          disabled={offline}
                          onClick={() => aoTratar(a, "FALSO_ALARME")}
                        >
                          Falso alarme
                        </button>
                      </div>
                    ) : (
                      <span className={`etiqueta-status etiqueta-status--${a.status.toLowerCase()}`}>
                        {ROTULO_STATUS[a.status]}
                        {a.tratado_por && <small> · {a.tratado_por}</small>}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
