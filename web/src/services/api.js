/*
 * api.js - Única camada que conhece as URLs do backend.
 *
 * Se a API mudar (ex.: migração para Node.js + JWT, como na documentação),
 * só este arquivo precisa ser alterado; as telas continuam iguais.
 */

const BASE = "/api";

/** fetch com JSON e erro legível. */
async function requisitar(caminho, opcoes = {}) {
  const resposta = await fetch(BASE + caminho, {
    headers: { "Content-Type": "application/json" },
    ...opcoes,
  });
  if (!resposta.ok) {
    const detalhe = await resposta.text();
    throw new Error(`Erro ${resposta.status}: ${detalhe}`);
  }
  return resposta.status === 204 ? null : resposta.json();
}

export const api = {
  status: () => requisitar("/status"),

  alertas: ({ status, tipo, limite = 100 } = {}) => {
    const params = new URLSearchParams({ limite });
    if (status) params.set("status", status);
    if (tipo) params.set("tipo", tipo);
    return requisitar(`/alertas?${params}`);
  },
  tratarAlerta: (id, status, tratadoPor) =>
    requisitar(`/alertas/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status, tratado_por: tratadoPor }),
    }),
  urlImagemAlerta: (id) => `${BASE}/alertas/${id}/imagem`,

  cameras: () => requisitar("/cameras"),
  atualizarCamera: (id, dados) =>
    requisitar(`/cameras/${id}`, { method: "PUT", body: JSON.stringify(dados) }),

  configuracao: () => requisitar("/configuracao"),
  salvarConfiguracao: (sensibilidade) =>
    requisitar("/configuracao", { method: "PUT", body: JSON.stringify({ sensibilidade }) }),

  contatos: () => requisitar("/contatos"),
  criarContato: (contato) =>
    requisitar("/contatos", { method: "POST", body: JSON.stringify(contato) }),
  removerContato: (id) => requisitar(`/contatos/${id}`, { method: "DELETE" }),

  urlVideo: () => `${BASE}/video`,
  urlWebSocket: () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${BASE}/ws`,
};
