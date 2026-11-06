/*
 * aviso.js - Chama a atenção do cuidador quando chega um alerta:
 *   1. som de sirene curto (Web Audio, sem arquivo de áudio);
 *   2. vibração no celular;
 *   3. notificação do sistema (aparece mesmo com a aba em segundo plano).
 *
 * Com o app totalmente FECHADO quem avisa é o Web Push (services/push.js + public/push-sw.js).
 */

let contextoAudio = null;

/** Navegadores só liberam áudio depois de um clique; chamamos isto no 1º clique do usuário. */
export function liberarAudio() {
  try {
    contextoAudio ??= new (window.AudioContext || window.webkitAudioContext)();
    if (contextoAudio.state === "suspended") contextoAudio.resume();
  } catch {
    /* navegador sem Web Audio */
  }
}

function tocarSirene() {
  if (!contextoAudio) return;
  const agora = contextoAudio.currentTime;
  // 3 bipes alternando grave/agudo: fácil de reconhecer e diferente de toques comuns.
  [0, 0.35, 0.7].forEach((inicio, i) => {
    const osc = contextoAudio.createOscillator();
    const ganho = contextoAudio.createGain();
    osc.type = "square";
    osc.frequency.value = i % 2 === 0 ? 880 : 660;
    ganho.gain.setValueAtTime(0.0001, agora + inicio);
    ganho.gain.exponentialRampToValueAtTime(0.25, agora + inicio + 0.02);
    ganho.gain.exponentialRampToValueAtTime(0.0001, agora + inicio + 0.3);
    osc.connect(ganho).connect(contextoAudio.destination);
    osc.start(agora + inicio);
    osc.stop(agora + inicio + 0.32);
  });
}

export async function pedirPermissaoNotificacao() {
  if (!("Notification" in window)) return "indisponivel";
  if (Notification.permission === "default") return Notification.requestPermission();
  return Notification.permission;
}

export function avisarAlerta(alerta) {
  tocarSirene();
  navigator.vibrate?.([400, 150, 400, 150, 400]);
  if ("Notification" in window && Notification.permission === "granted") {
    const titulo = alerta.tipo === "QUEDA" ? "Queda detectada" : "Pessoa no chão";
    new Notification(titulo, {
      body: `${alerta.camera_nome} · agora`,
      icon: "/icone.svg",
      tag: `alerta-${alerta.id}`,
      requireInteraction: true,
    });
  }
}
