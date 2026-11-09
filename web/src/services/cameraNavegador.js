/*
 * cameraNavegador.js - Usa a câmera DESTE aparelho (celular ou computador) como uma câmera do sistema.
 *
 * Como funciona (mesmo caminho do agente.py, só que o "agente" é a própria página):
 *   1. pede permissão ao navegador (getUserMedia), igual ao pedido de notificações;
 *   2. cria uma chave de agente pelo painel (só administrador) e registra a câmera;
 *   3. manda quadros JPEG ao painel: ~8 por segundo enquanto alguém assiste, 1 a cada 2 s sem espectador
 *      (o painel responde {"assistindo": true/false} a cada quadro);
 *   4. DETECTA A QUEDA AQUI MESMO: o MediaPipe (pose) roda na própria página ~5 vezes por segundo e o detectorQueda.js
 *      (tradução fiel do fall_detector.py) decide queda / pessoa no chão. O alerta sobe com a foto para /api/agente/alertas;
 *      o painel grava e avisa o push e o WhatsApp. Se o modelo não carregar, a câmera segue só transmitindo e o painel
 *      mostra "SÓ VÍDEO" (nunca finge que protege).
 *   5. a cada 3 s manda o status e a cada 10 s busca a configuração (sensibilidade, área da cama, câmera ligada).
 *
 * O controlador mora fora dos componentes React: a câmera continua ligada quando se troca de tela.
 * Ao parar, os quadros cessam, a câmera do aparelho é liberada e a chave do agente é revogada.
 *
 * Limites do navegador: a tela precisa ficar ligada e a página aberta (mantemos a tela acesa com o Wake Lock).
 */
import { useSyncExternalStore } from "react";
import { api } from "./api.js";
import { aplicarSensibilidade, configPadrao, DetectorQueda } from "./detectorQueda.js";

const FPS_COM_ESPECTADOR = 8;
const ESPERA_SEM_ESPECTADOR_MS = 2000;
const STATUS_MS = 3000;
const CONFIG_MS = 10000;
const LARGURA = 640;
const QUALIDADE = 0.65;
const DETECCAO_MS = 200; // ~5 análises por segundo
const FOTO_LARGURA = 960;
const FOTO_QUALIDADE = 0.8;
const MAX_TENTATIVAS_ALERTA = 6;
const CONFIANCA_ALERTA = 0.9;
const GRAVIDADE = { normal: 0, no_chao: 1, caindo: 1, alerta: 2 };

// deteccao: "desligada" | "carregando" | "ativa" | "indisponivel"
const PARADA = { fase: "parada", erro: "", nome: "", cameraId: null, assistindo: false, fps: 0, pausada: false, deteccao: "desligada", pessoas: 0, ultimoAlerta: null };

/** Carrega o MediaPipe só quando a câmera do aparelho é ligada (o pacote é grande e não vai no carregamento do painel). */
async function criarPoseLandmarker() {
  const { FilesetResolver, PoseLandmarker } = await import("@mediapipe/tasks-vision");
  const arquivos = await FilesetResolver.forVisionTasks("/mediapipe");
  const opcoes = (delegate) => ({
    baseOptions: { modelAssetPath: "/modelos/pose_landmarker_lite.task", delegate },
    runningMode: "VIDEO",
    numPoses: 3,
    minPoseDetectionConfidence: 0.4,
    minPosePresenceConfidence: 0.4,
    minTrackingConfidence: 0.4,
  });
  try {
    return await PoseLandmarker.createFromOptions(arquivos, opcoes("GPU"));
  } catch {
    return PoseLandmarker.createFromOptions(arquivos, opcoes("CPU")); // aparelho sem GPU compatível
  }
}

function blobParaBase64(blob) {
  return new Promise((resolver, rejeitar) => {
    const leitor = new FileReader();
    leitor.onload = () => resolver(String(leitor.result).split(",")[1] ?? "");
    leitor.onerror = () => rejeitar(leitor.error);
    leitor.readAsDataURL(blob);
  });
}

export function mensagemDoErro(erro) {
  switch (erro?.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Permissão negada. Libere a câmera para este site nas configurações do navegador e tente de novo.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "Nenhuma câmera encontrada neste aparelho.";
    case "NotReadableError":
    case "AbortError":
      return "A câmera está em uso por outro programa. Feche-o e tente de novo.";
    default:
      return typeof erro?.detalhe === "string" ? erro.detalhe : "Não foi possível ligar a câmera deste aparelho.";
  }
}

/** O nome do agente só aceita letras, números, espaço, ponto, hífen e sublinhado. */
function nomeDeAgente(nome) {
  const limpo = nome.replace(/[^\p{L}\p{N} ._-]/gu, "").trim();
  return `Navegador - ${limpo || "aparelho"}`.slice(0, 80);
}

class ControladorCamera {
  constructor() {
    this.estado = PARADA;
    this.ouvintes = new Set();
    this.stream = null;
    this._video = null;
    this._canvas = document.createElement("canvas");
    this._token = null;
    this._agente = null;
    this._timers = [];
    this._parado = true;
    this._quadrosDesdeStatus = 0;
    this._ultimoStatus = 0;
    this._wakeLock = null;
    this._pose = null;
    this._detector = null;
    this._detectorDim = "";
    this._cfgQueda = configPadrao();
    this._area = [];
    this._ultimoTempoVideo = -1;
    this._pessoas = [];
    this._pendentes = [];
    this.inscrever = this.inscrever.bind(this);
    this.obter = this.obter.bind(this);
  }

  suportado() {
    return Boolean(navigator.mediaDevices?.getUserMedia);
  }

  inscrever(ouvinte) {
    this.ouvintes.add(ouvinte);
    return () => this.ouvintes.delete(ouvinte);
  }

  obter() {
    return this.estado;
  }

  _definir(parcial) {
    this.estado = { ...this.estado, ...parcial };
    this.ouvintes.forEach((o) => o());
  }

  async _chamar(caminho, { json, ...opcoes } = {}) {
    const resposta = await fetch(`/api${caminho}`, {
      ...opcoes,
      headers: { Authorization: `Bearer ${this._token}`, ...(json ? { "Content-Type": "application/json" } : {}), ...opcoes.headers },
      body: json ? JSON.stringify(json) : opcoes.body,
    });
    if (resposta.status === 401 || resposta.status === 404) {
      const erro = new Error("revogado");
      erro.revogado = true;
      throw erro;
    }
    if (!resposta.ok) throw new Error(String(resposta.status));
    return resposta.status === 204 ? null : resposta.json();
  }

  async iniciar({ nome, local = "", facing = "user" }) {
    if (!["parada", "erro"].includes(this.estado.fase)) return;
    nome = nome.trim() || "Câmera do aparelho";
    this._definir({ ...PARADA, fase: "pedindo", nome });
    try {
      // A janela de permissão do navegador aparece aqui.
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
    } catch (erro) {
      return this._falhar(mensagemDoErro(erro));
    }
    this._video = document.createElement("video");
    this._video.muted = true;
    this._video.playsInline = true;
    this._video.srcObject = this.stream;
    await this._video.play().catch(() => {});

    this._definir({ fase: "conectando" });
    try {
      const nomeAgente = nomeDeAgente(nome);
      const existente = (await api.agentes()).find((a) => a.nome === nomeAgente);
      const agente = existente ? await api.novaChaveAgente(existente.id) : await api.criarAgente(nomeAgente);
      this._agente = { id: agente.id };
      this._token = agente.token;
      const camera = await this._chamar("/agente/camera", { method: "POST", json: { nome, local } });
      this._definir({ cameraId: camera.id });
    } catch (erro) {
      await this._encerrar();
      return this._falhar(mensagemDoErro(erro));
    }

    this._parado = false;
    this._quadrosDesdeStatus = 0;
    this._ultimoStatus = performance.now();
    this._definir({ fase: "transmitindo" });
    await this._pedirTelaAcesa();
    document.addEventListener("visibilitychange", this._aoMudarVisibilidade);
    this._laco(() => this._passoVideo(), 0);
    this._laco(() => this._passoStatus(), STATUS_MS);
    this._iniciarDeteccao();
  }

  async _iniciarDeteccao() {
    this._definir({ deteccao: "carregando" });
    try {
      const pose = await criarPoseLandmarker();
      if (this._parado) return pose.close();
      this._pose = pose;
      this._definir({ deteccao: "ativa" });
      this._laco(() => this._passoDeteccao(), 0);
    } catch {
      // Sem o modelo não há proteção: o status avisa "só vídeo" ao painel.
      if (!this._parado) this._definir({ deteccao: "indisponivel" });
    }
  }

  _detectorAtual(largura, altura) {
    const dim = `${largura}x${altura}`;
    if (this._detector && this._detectorDim === dim) return this._detector;
    this._detectorDim = dim;
    this._detector = new DetectorQueda(largura, altura, this._cfgQueda, 0.3);
    this._detector.definirZonasCama(this._area);
    return this._detector;
  }

  async _passoDeteccao() {
    const v = this._video;
    if (this.estado.pausada || !this._pose || !v || v.readyState < 2 || !v.videoWidth) return DETECCAO_MS;
    await this._reenviarPendentes();
    if (v.currentTime === this._ultimoTempoVideo) return DETECCAO_MS; // quadro repetido
    this._ultimoTempoVideo = v.currentTime;

    const inicio = performance.now();
    const largura = v.videoWidth;
    const altura = v.videoHeight;
    const resultado = this._pose.detectForVideo(v, inicio);
    const poses = (resultado.landmarks ?? []).map((pessoa) => pessoa.map((p) => [p.x * largura, p.y * altura, p.visibility ?? 0]));
    const { pessoas, alertas } = this._detectorAtual(largura, altura).processar(poses, inicio / 1000);
    this._pessoas = pessoas;
    if (pessoas.length !== this.estado.pessoas) this._definir({ pessoas: pessoas.length });

    for (const alerta of alertas) await this._registrarAlerta(alerta);
    return Math.max(0, DETECCAO_MS - (performance.now() - inicio));
  }

  /** Foto do momento do alerta (quadro inteiro, maior que o do vídeo ao vivo). */
  async _fotoDoMomento() {
    const v = this._video;
    if (!v || !v.videoWidth) return null;
    const c = document.createElement("canvas");
    const escala = Math.min(1, FOTO_LARGURA / v.videoWidth);
    c.width = Math.round(v.videoWidth * escala);
    c.height = Math.round(v.videoHeight * escala);
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    const blob = await new Promise((resolver) => c.toBlob(resolver, "image/jpeg", FOTO_QUALIDADE));
    return blob ? blobParaBase64(blob) : null;
  }

  async _registrarAlerta(alerta) {
    let foto = null;
    try {
      foto = await this._fotoDoMomento();
    } catch {
      /* alerta sem foto é melhor do que sem alerta */
    }
    const item = {
      corpo: {
        camera_id: this.estado.cameraId,
        track_id: alerta.id,
        tipo: alerta.tipo,
        confianca: CONFIANCA_ALERTA,
        imagem_jpeg_b64: foto,
      },
      tentativas: 0,
    };
    this._definir({ ultimoAlerta: { tipo: alerta.tipo, quando: Date.now() } });
    this._pendentes.push(item);
    await this._reenviarPendentes();
  }

  /** Tenta mandar os alertas que ainda não subiram (rede caiu); só esta página guarda a fila. */
  async _reenviarPendentes() {
    for (const item of [...this._pendentes]) {
      try {
        await this._chamar("/agente/alertas", { method: "POST", json: item.corpo });
        this._pendentes.splice(this._pendentes.indexOf(item), 1);
      } catch (erro) {
        if (erro?.revogado) throw erro;
        item.tentativas += 1;
        if (item.tentativas >= MAX_TENTATIVAS_ALERTA) this._pendentes.splice(this._pendentes.indexOf(item), 1);
      }
    }
  }

  _aoMudarVisibilidade = () => {
    if (document.visibilityState === "visible" && !this._parado) this._pedirTelaAcesa();
  };

  async _pedirTelaAcesa() {
    try {
      this._wakeLock = (await navigator.wakeLock?.request("screen")) ?? null;
    } catch {
      /* sem suporte ou negado: a tela pode apagar */
    }
  }

  /** Repete `passo` para sempre; o passo devolve a espera (ms) até a próxima vez. */
  _laco(passo, esperaInicial) {
    const rodar = async () => {
      if (this._parado) return;
      let espera = 1000;
      try {
        espera = await passo();
      } catch (erro) {
        if (erro?.revogado) return this.parar("Esta câmera foi desativada, revogada ou excluída no painel.");
      }
      if (!this._parado) this._timers.push(setTimeout(rodar, espera));
    };
    this._timers.push(setTimeout(rodar, esperaInicial));
  }

  async _passoVideo() {
    const inicio = performance.now();
    let assistindo = false;
    if (!this.estado.pausada) assistindo = await this._enviarQuadro();
    if (assistindo !== this.estado.assistindo) this._definir({ assistindo });
    const ritmo = assistindo ? 1000 / FPS_COM_ESPECTADOR : ESPERA_SEM_ESPECTADOR_MS;
    return Math.max(0, ritmo - (performance.now() - inicio));
  }

  async _enviarQuadro() {
    const v = this._video;
    if (!v || v.readyState < 2 || !v.videoWidth) return false;
    const escala = Math.min(1, LARGURA / v.videoWidth);
    this._canvas.width = Math.round(v.videoWidth * escala);
    this._canvas.height = Math.round(v.videoHeight * escala);
    this._canvas.getContext("2d").drawImage(v, 0, 0, this._canvas.width, this._canvas.height);
    const blob = await new Promise((resolver) => this._canvas.toBlob(resolver, "image/jpeg", QUALIDADE));
    if (!blob) return false;
    const resposta = await this._chamar(`/agente/quadro?camera_id=${this.estado.cameraId}`, {
      method: "POST",
      headers: { "Content-Type": "image/jpeg" },
      body: blob,
    });
    this._quadrosDesdeStatus += 1;
    return Boolean(resposta?.assistindo);
  }

  async _passoStatus() {
    const agora = performance.now();
    const fps = this._quadrosDesdeStatus / Math.max(1, (agora - this._ultimoStatus) / 1000);
    this._quadrosDesdeStatus = 0;
    this._ultimoStatus = agora;
    this._definir({ fps: Math.round(fps * 10) / 10 });
    await this._chamar("/agente/status", {
      method: "POST",
      json: {
        camera_id: this.estado.cameraId,
        fps,
        pessoas: this._pessoas.filter((p) => p.temPose).length,
        estado: this._estadoGeral(),
        camera_online: true,
        deteccao: this.estado.deteccao === "ativa",
      },
    });
    if (agora - (this._ultimaConfig ?? 0) >= CONFIG_MS) {
      this._ultimaConfig = agora;
      const config = await this._chamar(`/agente/config?camera_id=${this.estado.cameraId}`);
      if (Boolean(!config.ativa) !== this.estado.pausada) this._definir({ pausada: !config.ativa });
      aplicarSensibilidade(this._cfgQueda, config.sensibilidade ?? 0.65); // mesma referência: vale na hora
      this._area = Array.isArray(config.area_cama) ? config.area_cama : [];
      this._detector?.definirZonasCama(this._area);
    }
    return STATUS_MS;
  }

  _estadoGeral() {
    const pior = this._pessoas.reduce((m, p) => Math.max(m, GRAVIDADE[p.estado] ?? 0), 0);
    return pior >= 2 ? "alerta" : pior === 1 ? "atencao" : "normal";
  }

  _falhar(mensagem) {
    this._definir({ ...PARADA, fase: "erro", erro: mensagem });
  }

  async _encerrar() {
    this._parado = true;
    this._timers.forEach(clearTimeout);
    this._timers = [];
    document.removeEventListener("visibilitychange", this._aoMudarVisibilidade);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this._video = null;
    try {
      this._pose?.close();
    } catch {
      /* já fechado */
    }
    this._pose = null;
    this._detector = null;
    this._detectorDim = "";
    this._pessoas = [];
    this._pendentes = [];
    this._ultimoTempoVideo = -1;
    try {
      await this._wakeLock?.release();
    } catch {
      /* já liberado */
    }
    this._wakeLock = null;
    if (this._agente) {
      try {
        await api.atualizarAgente(this._agente.id, false); // a chave não fica valendo depois de parar
      } catch {
        /* sem rede ou sem permissão: a chave só existia nesta página */
      }
    }
    this._agente = null;
    this._token = null;
  }

  async parar(motivo = "") {
    await this._encerrar();
    this._definir({ ...PARADA, erro: motivo, fase: motivo ? "erro" : "parada" });
  }
}

export const controladorCamera = new ControladorCamera();

export function useCameraDoNavegador() {
  const estado = useSyncExternalStore(controladorCamera.inscrever, controladorCamera.obter);
  return {
    ...estado,
    suportado: controladorCamera.suportado(),
    stream: controladorCamera.stream,
    iniciar: (opcoes) => controladorCamera.iniciar(opcoes),
    parar: () => controladorCamera.parar(),
  };
}
