/*
 * Pictogramas.jsx - Figuras grandes da tela Monitor (desenho próprio, em SVG, no estilo das placas de segurança).
 *   - FiguraQueda: pessoa caindo, com traços de impacto (alerta).
 *   - FiguraEmPe: pessoa em pé (tudo bem).
 *   - FiguraSemSinal: câmera sem sinal.
 * Usam currentColor: a cor vem do CSS do quadro (vermelho, verde, cinza).
 */

const traco = { stroke: "currentColor", strokeLinecap: "round", strokeLinejoin: "round", fill: "none" };

export function FiguraQueda({ tamanho = 120, ...props }) {
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 120 120" aria-hidden="true" {...props}>
      {/* traços de "impacto" perto da cabeça */}
      <g {...traco} strokeWidth="5">
        <line x1="22" y1="14" x2="29" y2="23" />
        <line x1="38" y1="5" x2="40" y2="16" />
        <line x1="12" y1="31" x2="23" y2="33" />
      </g>
      <circle cx="50" cy="32" r="11" fill="currentColor" />
      <g {...traco}>
        {/* tronco inclinado */}
        <line x1="50" y1="48" x2="66" y2="78" strokeWidth="15" />
        {/* braços abertos tentando se segurar */}
        <polyline points="55,54 78,40 88,22" strokeWidth="9" />
        <polyline points="50,56 30,54 20,66" strokeWidth="9" />
        {/* uma perna escorregando para frente, a outra dobrada */}
        <polyline points="66,78 90,70 108,76" strokeWidth="10" />
        <polyline points="64,80 56,98 66,110" strokeWidth="10" />
      </g>
      <ellipse cx="62" cy="114" rx="40" ry="4" fill="currentColor" opacity="0.25" />
    </svg>
  );
}

export function FiguraEmPe({ tamanho = 120, ...props }) {
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 120 120" aria-hidden="true" {...props}>
      <circle cx="60" cy="20" r="11" fill="currentColor" />
      <g {...traco}>
        <line x1="60" y1="38" x2="60" y2="72" strokeWidth="15" />
        <polyline points="60,44 46,58 42,74" strokeWidth="9" />
        <polyline points="60,44 74,58 78,74" strokeWidth="9" />
        <line x1="56" y1="74" x2="50" y2="106" strokeWidth="10" />
        <line x1="64" y1="74" x2="70" y2="106" strokeWidth="10" />
      </g>
      <ellipse cx="60" cy="112" rx="30" ry="4" fill="currentColor" opacity="0.25" />
    </svg>
  );
}

export function FiguraSemSinal({ tamanho = 120, ...props }) {
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 120 120" aria-hidden="true" {...props}>
      <g {...traco} strokeWidth="7">
        <rect x="18" y="40" width="58" height="42" rx="8" />
        <polyline points="76,54 100,42 100,80 76,68" />
        <line x1="14" y1="100" x2="104" y2="22" />
      </g>
    </svg>
  );
}
