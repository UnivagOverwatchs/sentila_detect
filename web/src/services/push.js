/*
 * push.js - Cadastra este aparelho para receber alertas com o app fechado (Web Push).
 * Pré-requisitos do navegador: HTTPS (ou localhost), service worker e permissão de notificação.
 */
import { api } from "./api.js";

export function pushDisponivel() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function chaveParaBytes(base64url) {
  const preenchida = base64url + "=".repeat((4 - (base64url.length % 4)) % 4);
  const bruto = atob(preenchida.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(bruto, (c) => c.charCodeAt(0));
}

/** Pede permissão, cria a assinatura e envia para a API. Devolve "ativo" ou o motivo da falha. */
export async function ativarPush() {
  if (!pushDisponivel()) return "indisponivel";
  const permissao = await Notification.requestPermission();
  if (permissao !== "granted") return permissao;
  try {
    const { chave } = await api.chavePush();
    const registro = await navigator.serviceWorker.ready;
    const assinatura =
      (await registro.pushManager.getSubscription()) ??
      (await registro.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: chaveParaBytes(chave) }));
    await api.salvarAssinaturaPush(assinatura.toJSON());
    return "ativo";
  } catch {
    return "erro";
  }
}
