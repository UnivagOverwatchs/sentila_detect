/*
 * Icones.jsx - Ícones em SVG embutido (traço no estilo Lucide).
 * Sem biblioteca externa: menos dependências e funciona offline.
 */

function Icone({ children, tamanho = 18, ...props }) {
  return (
    <svg
      width={tamanho}
      height={tamanho}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export const IconeEscudo = (p) => (
  <Icone {...p}>
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    <path d="m9 12 2 2 4-4" />
  </Icone>
);
export const IconeCasa = (p) => (
  <Icone {...p}>
    <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    <path d="M9 22V12h6v10" />
  </Icone>
);
export const IconeRelogio = (p) => (
  <Icone {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 6v6l4 2" />
  </Icone>
);
export const IconeAjustes = (p) => (
  <Icone {...p}>
    <path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3" />
    <path d="M14 2v4M8 10v4M16 18v4" />
  </Icone>
);
export const IconeTelefone = (p) => (
  <Icone {...p}>
    <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z" />
  </Icone>
);
export const IconeFechar = (p) => (
  <Icone {...p}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Icone>
);
export const IconeCheck = (p) => (
  <Icone {...p}>
    <path d="M20 6 9 17l-5-5" />
  </Icone>
);
export const IconeAlerta = (p) => (
  <Icone {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 8v4M12 16h.01" />
  </Icone>
);
export const IconeCamera = (p) => (
  <Icone {...p}>
    <path d="m22 8-6 4 6 4V8z" />
    <rect x="2" y="6" width="14" height="12" rx="2" />
  </Icone>
);
export const IconePessoas = (p) => (
  <Icone {...p}>
    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
  </Icone>
);
export const IconeAtividade = (p) => (
  <Icone {...p}>
    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
  </Icone>
);
export const IconeMais = (p) => (
  <Icone {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icone>
);
export const IconeSino = (p) => (
  <Icone {...p}>
    <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
    <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
  </Icone>
);
export const IconeImagem = (p) => (
  <Icone {...p}>
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="9" cy="9" r="2" />
    <path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21" />
  </Icone>
);
