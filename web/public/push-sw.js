/*
 * push-sw.js - Trecho do service worker que trata o Web Push (importado pelo sw.js gerado pelo vite-plugin-pwa).
 * Mostra a notificação mesmo com o aplicativo fechado e abre o painel ao tocar nela.
 * A `tag` é a mesma usada pela notificação interna do app: se os dois chegarem, um substitui o outro.
 */
self.addEventListener("push", (evento) => {
  let dados = {};
  try {
    dados = evento.data ? evento.data.json() : {};
  } catch {
    dados = { titulo: "Alerta", corpo: evento.data ? evento.data.text() : "" };
  }
  evento.waitUntil(
    self.registration.showNotification(dados.titulo || "Alerta", {
      body: dados.corpo || "",
      icon: "/icone.svg",
      badge: "/icone.svg",
      tag: `alerta-${dados.alerta_id ?? "novo"}`,
      requireInteraction: true,
      vibrate: [400, 150, 400, 150, 400],
      data: { url: "/" },
    })
  );
});

self.addEventListener("notificationclick", (evento) => {
  evento.notification.close();
  evento.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((janelas) => {
      for (const janela of janelas) {
        if ("focus" in janela) return janela.focus();
      }
      return self.clients.openWindow("/");
    })
  );
});
