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
    credentials: "same-origin",
    ...opcoes,
  });
  if (!resposta.ok) {
    // 401 fora do login = sessão expirada: a tela volta para o login.
    if (resposta.status === 401 && caminho !== "/login") window.dispatchEvent(new Event("sentinela:sessao-expirada"));
    const detalhe = await resposta.text();
    const erro = new Error(`Erro ${resposta.status}: ${detalhe}`);
    erro.status = resposta.status;
    try {
      erro.detalhe = JSON.parse(detalhe).detail;
    } catch {
      /* resposta sem JSON */
    }
    throw erro;
  }
  return resposta.status === 204 ? null : resposta.json();
}

export const api = {
  eu: () => requisitar("/eu"),
  login: (usuario, senha) => requisitar("/login", { method: "POST", body: JSON.stringify({ usuario, senha }) }),
  logout: () => requisitar("/logout", { method: "POST" }),
  usuarios: () => requisitar("/usuarios"),
  criarUsuario: (dados) => requisitar("/usuarios", { method: "POST", body: JSON.stringify(dados) }),
  atualizarUsuario: (id, dados) => requisitar(`/usuarios/${id}`, { method: "PATCH", body: JSON.stringify(dados) }),

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

  salvarAreaCama: (id, poligonos) =>
    requisitar(`/cameras/${id}/area-cama`, { method: "PUT", body: JSON.stringify({ poligonos }) }),

  configuracao: () => requisitar("/configuracao"),
  salvarConfiguracao: (sensibilidade) =>
    requisitar("/configuracao", { method: "PUT", body: JSON.stringify({ sensibilidade }) }),

  contatos: () => requisitar("/contatos"),
  criarContato: (contato) =>
    requisitar("/contatos", { method: "POST", body: JSON.stringify(contato) }),
  removerContato: (id) => requisitar(`/contatos/${id}`, { method: "DELETE" }),

  chavePush: () => requisitar("/push/chave"),
  salvarAssinaturaPush: (assinatura) =>
    requisitar("/push/assinaturas", { method: "POST", body: JSON.stringify(assinatura) }),
  aparelhos: () => requisitar("/push/aparelhos"),
  renomearAparelho: (id, nome) =>
    requisitar(`/push/aparelhos/${id}`, { method: "PATCH", body: JSON.stringify({ nome }) }),
  removerAparelho: (id) => requisitar(`/push/aparelhos/${id}`, { method: "DELETE" }),

  urlQuadro: () => `${BASE}/quadro`,
  urlWebSocket: () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${BASE}/ws`,
};
