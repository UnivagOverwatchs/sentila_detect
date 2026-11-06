/*
 * formato.js - Textos exibidos na interface (datas, tipos, status).
 * Centralizado para manter o mesmo vocabulário em todas as telas.
 */

export const ROTULO_TIPO = {
  QUEDA: "Queda",
  MOVIMENTO_ANOMALO: "Pessoa no chão",
};

export const TITULO_TIPO = {
  QUEDA: "Possível queda detectada",
  MOVIMENTO_ANOMALO: "Pessoa no chão há alguns segundos",
};

export const ROTULO_STATUS = {
  PENDENTE: "Pendente",
  RESOLVIDO: "Resolvido",
  FALSO_ALARME: "Falso alarme",
};

/** "14:32" */
export function hora(iso) {
  return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

/** "Hoje", "Ontem" ou "04/11" */
export function dia(iso) {
  const data = new Date(iso);
  const hoje = new Date();
  const ontem = new Date();
  ontem.setDate(hoje.getDate() - 1);
  if (data.toDateString() === hoje.toDateString()) return "Hoje";
  if (data.toDateString() === ontem.toDateString()) return "Ontem";
  return data.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

/** "há 12 s", "há 3 min", "há 2 h" */
export function haQuantoTempo(iso) {
  const segundos = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (segundos < 60) return `há ${segundos} s`;
  if (segundos < 3600) return `há ${Math.round(segundos / 60)} min`;
  return `há ${Math.round(segundos / 3600)} h`;
}
