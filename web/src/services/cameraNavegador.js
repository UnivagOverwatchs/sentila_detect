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
 *
 * VISÃO LOCAL ("espelho"): neste aparelho a imagem é mostrada direto da câmera (componente VideoLocal), em alta
 * resolução e sem atraso, com o esqueleto desenhado por cima (desenharSobreposicao). O que vai para o painel continua
 * reduzido (LARGURA/QUALIDADE) para não pesar na rede: só quem está aqui vê a imagem cheia.
 */
import { useSyncExternalStore } from "react";
import { api } from "./api.js";
import { aplicarSensibilidade, configPadrao, DetectorQueda } from "./detectorQueda.js";
import { FilaAlertas } from "./filaAlertas.js";

const FPS_COM_ESPECTADOR = 8;
const ESPERA_SEM_ESPECTADOR_MS = 2000;
const STATUS_MS = 3000;
const CONFIG_MS = 10000;
const LARGURA = 640;
const QUALIDADE = 0.65;
const DETECCAO_MS = 100; // até ~10 análises por segundo, a câmera está aqui mesmo (aparelho lento espera mais: ver _passoDeteccao)
// Pedido à câmera: o máximo útil para a visão local. Os quadros enviados ao painel são reduzidos para LARGURA.
const RESOLUCAO_LOCAL = { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30, max: 30 } };
const LARGURA_DETECCAO = 480; // o modelo reduz a imagem para 256 px de qualquer jeito: mandar o vídeo inteiro só gasta processador
const FOTO_LARGURA = 960;
const FOTO_QUALIDADE = 0.8;
const TEMPO_LIMITE_REDE_MS = 8000; // nenhuma chamada fica pendurada: rede ruim vira erro e a fila tenta de novo
const FILA_MS = 1000; // a fila de alertas é conferida a cada segundo, num laço separado da detecção
const CHAVE_APARELHO = "sentinela.aparelho";
// Ligações do esqueleto (mesmas de sentinela_pose/pontos.py).
const LIGACOES = [[11, 12], [23, 24], [11, 23], [12, 24], [23, 25], [25, 27], [24, 26], [26, 28], [11, 13], [13, 15], [12, 14], [14, 16]];
const GRAVIDADE ={ normal: 0, no_chao: 1, caindo: 1, alerta: 2 };

// deteccao: "desligada" | "carregando" | "ativa" | "indisponivel"
const PARADA = { fase: "parada", erro: "", nome: "", cameraId: null, facing: "user", assistindo: false, fps: 0, pausada: false, deteccao: "desligada", processador: "", msDeteccao: 0, pessoas: 0, achadas: 0, ultimoAlerta: null };

/** Carrega o MediaPipe só quando a câmera do aparelho é ligada (o pacote é grande e não vai no carregamento do painel). */
async function criarPoseLandmarker(somenteCpu = false) {
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
    if (somenteCpu) throw new Error("cpu");
    return { pose: await PoseLandmarker.createFromOptions(arquivos, opcoes("GPU")), processador: "GPU" };
  } catch {
    // aparelho sem GPU compatível
    return { pose: await PoseLandmarker.createFromOptions(arquivos, opcoes("CPU")), processador: "CPU" };
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

/** Armazenamento do aparelho que nunca derruba a câmera (aba anônima/bloqueado = segue sem guardar). */
function armazenamentoSeguro() {
  try {
    const teste = "__sentinela__";
    localStorage.setItem(teste, "1");
    localStorage.removeItem(teste);
    return localStorage;
  } catch {
    return null;
  }
}

/** Identificador aleatório DESTE aparelho: dois celulares com o mesmo nome de câmera não derrubam um ao outro. */
function idDoAparelho() {
  const armazenamento = armazenamentoSeguro();
  let id = armazenamento?.getItem(CHAVE_APARELHO);
  if (!id || !/^[a-z0-9]{12,40}$/.test(id)) {
    const bytes = crypto.getRandomValues(new Uint8Array(12));
    id = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    armazenamento?.setItem(CHAVE_APARELHO, id);
  }
  return id;
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
    this._fila = null;
    this._aparelho = null;
    this._desenho = null;
    this._canvasDeteccao = null;
    this._custoMedio = 0;
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
      signal: AbortSignal.timeout?.(TEMPO_LIMITE_REDE_MS),
    });
    if (resposta.status === 401 || resposta.status === 404) {
      const erro = new Error("revogado");
      erro.revogado = true;
      erro.status = resposta.status;
      throw erro;
    }
    if (!resposta.ok) {
      const erro = new Error(String(resposta.status));
      erro.status = resposta.status;
      throw erro;
    }
    return resposta.status === 204 ? null : resposta.json();
  }

  async iniciar({ nome, local = "", facing = "user" }) {
    if (!["parada", "erro"].includes(this.estado.fase)) return;
    nome = nome.trim() || "Câmera do aparelho";
    this._definir({ ...PARADA, fase: "pedindo", nome, facing });
    try {
      // A janela de permissão do navegador aparece aqui.
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing, ...RESOLUCAO_LOCAL },
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
      this._aparelho = idDoAparelho();
      const agente = await api.agenteNavegador(this._aparelho, nome);
      this._agente = { id: agente.id };
      this._token = agente.token;
      // A fila carrega alertas que ficaram guardados de antes (página recarregada sem rede, por exemplo).
      this._fila = new FilaAlertas({
        enviar: (corpo) => this._chamar("/agente/alertas", { method: "POST", json: corpo }),
        armazenamento: armazenamentoSeguro(),
      });
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
    this._laco(() => this._passoFila(), 0); // envio de alertas: separado da detecção, nunca a faz esperar
    this._iniciarDeteccao();
  }

  async _iniciarDeteccao() {
    this._definir({ deteccao: "carregando" });
    try {
      const { pose, processador } = await criarPoseLandmarker();
      if (this._parado) return pose.close();
      this._pose = pose;
      this._definir({ deteccao: "ativa", processador });
      this._laco(() => this._passoDeteccao(), 0);
    } catch {
      // Sem o modelo não há proteção: o status avisa "só vídeo" ao painel.
      if (!this._parado) this._definir({ deteccao: "indisponivel" });
    }
  }

  async _trocarParaCpu() {
    try {
      const { pose } = await criarPoseLandmarker(true);
      if (this._parado) return pose.close();
      const antiga = this._pose;
      this._pose = pose;
      antiga?.close();
      this._custoMedio = 0;
      this._amostras = 0;
      this._definir({ processador: "CPU", msDeteccao: 0 });
    } catch {
      /* fica na GPU mesmo */
    } finally {
      this._trocandoProcessador = false;
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
    if (v.currentTime === this._ultimoTempoVideo) return DETECCAO_MS; // quadro repetido
    this._ultimoTempoVideo = v.currentTime;

    const inicio = performance.now();
    const largura = v.videoWidth;
    const altura = v.videoHeight;
    // Reduz o quadro antes de analisar: o resultado vem normalizado (0 a 1), então vale para o vídeo original.
    const cd = this._canvasDeteccao ?? (this._canvasDeteccao = document.createElement("canvas"));
    const escala = Math.min(1, LARGURA_DETECCAO / largura);
    cd.width = Math.round(largura * escala);
    cd.height = Math.round(altura * escala);
    cd.getContext("2d").drawImage(v, 0, 0, cd.width, cd.height);
    const resultado = this._pose.detectForVideo(cd, inicio);
    const poses = (resultado.landmarks ?? []).map((pessoa) => pessoa.map((p) => [p.x * largura, p.y * altura, p.visibility ?? 0]));
    const { pessoas, alertas } = this._detectorAtual(largura, altura).processar(poses, inicio / 1000);
    this._pessoas = pessoas;
    // Desenho: toda pose achada pelo modelo; as que o detector aceitou (tronco inteiro na imagem) levam cor e estado.
    const aceitas = new Map(pessoas.filter((p) => p.temPose).map((p) => [p.pontos, p]));
    this._desenho = { largura, altura, poses: poses.map((pontos) => ({ pontos, pessoa: aceitas.get(pontos) ?? null })) };
    const contadas = aceitas.size;
    if (contadas !== this.estado.pessoas) this._definir({ pessoas: contadas, achadas: poses.length });
    else if (poses.length !== this.estado.achadas) this._definir({ achadas: poses.length });

    for (const alerta of alertas) await this._registrarAlerta(alerta);
    // Aparelho lento: espera o dobro do que a análise levou, para sobrar processador ao envio do vídeo (senão trava).
    const custo = performance.now() - inicio;
    this._amostras = (this._amostras ?? 0) + 1;
    if (this._amostras > 3) this._custoMedio = this._custoMedio ? 0.7 * this._custoMedio + 0.3 * custo : custo; // as 3 primeiras incluem o aquecimento do modelo
    // A "GPU" do navegador às vezes é emulada por software e fica MUITO mais lenta que a CPU: se passar de 300 ms, troca.
    if (this.estado.processador === "GPU" && this._amostras >= 8 && this._custoMedio > 300 && !this._trocandoProcessador) {
      this._trocandoProcessador = true;
      this._trocarParaCpu();
    }
    const ms = Math.round(this._custoMedio);
    if (Math.abs(ms - this.estado.msDeteccao) >= 5) this._definir({ msDeteccao: ms });
    return Math.max(DETECCAO_MS - custo, this._custoMedio * 2 - custo, 0);
  }

  /** Foto do momento do alerta (quadro inteiro, maior que o do vídeo ao vivo). */
  async _fotoDoMomento() {
    const v = this._video;
    if (!v || !v.videoWidth) return null;
    const c = document.createElement("canvas");
    const escala = Math.min(1, FOTO_LARGURA / v.videoWidth);
    c.width = Math.round(v.videoWidth * escala);
    c.height = Math.round(v.videoHeight * escala);
    const ctx = c.getContext("2d");
    ctx.drawImage(v, 0, 0, c.width, c.height);
    this._desenharEsqueletos(ctx, c.width, c.height, true); // a foto do alerta mostra o esqueleto e os rótulos
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
        confianca: Math.min(Math.max(alerta.angulo / 90, 0), 1), // mesmo critério do agente: quão horizontal está o tronco
        imagem_jpeg_b64: foto,
        detalhes: { ...alerta.detalhes, origem: "navegador" },
      },
    };
    this._definir({ ultimoAlerta: { tipo: alerta.tipo, quando: Date.now() } });
    this._fila.adicionar(item.corpo);
    this._fila.processar().catch(() => {}); // tenta já; se falhar, o laço da fila tenta de novo (sem segurar a detecção)
  }

  /** Laço da fila de alertas: 401 sobe para o _laco, que para a câmera (o alerta continua guardado no aparelho). */
  async _passoFila() {
    await this._fila?.processar();
    return FILA_MS;
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
    const ctx = this._canvas.getContext("2d");
    ctx.drawImage(v, 0, 0, this._canvas.width, this._canvas.height);
    this._desenharEsqueletos(ctx, this._canvas.width, this._canvas.height);
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

  /**
   * Esqueleto por cima do vídeo ao vivo e da foto do alerta (igual ao agente em Python: "ID1 ALERTA 91°").
   * Verde = pessoa normal; amarelo = caindo (inclinando/descendo rápido) ou deitada sem confirmar; vermelho = queda confirmada; cinza = pessoa vista, mas SEM o tronco inteiro
   * na imagem (ombros ou quadris cortados): o detector não consegue avaliar e não conta essa pessoa.
   */
  /** Visão local: limpa o canvas transparente e desenha só o esqueleto (o vídeo fica no <video> embaixo). */
  desenharSobreposicao(ctx, largura, altura, espelhar = false) {
    ctx.clearRect(0, 0, largura, altura);
    this._desenharEsqueletos(ctx, largura, altura, false, espelhar);
  }

  // espelhar: a câmera frontal é mostrada como espelho; os pontos trocam de lado, mas o texto continua legível.
  _desenharEsqueletos(ctx, largura, altura, momentoDoAlerta = false, espelhar = false) {
    const d = this._desenho;
    if (!d || this.estado.deteccao !== "ativa") return;
    if (momentoDoAlerta) {
      ctx.strokeStyle = "#ef4444";
      ctx.lineWidth = 6;
      ctx.strokeRect(3, 3, largura - 6, altura - 6);
      ctx.fillStyle = "rgba(15,23,42,0.75)";
      ctx.fillRect(10, 10, 190, 28);
      ctx.fillStyle = "#fff";
      ctx.font = "bold 16px sans-serif";
      ctx.fillText("Momento do alerta", 18, 30);
    }
    const ex = largura / d.largura;
    const ey = altura / d.altura;
    const px = (x) => (espelhar ? largura - x * ex : x * ex); // posição horizontal na tela (já espelhada se for o caso)
    ctx.lineWidth = 3;
    ctx.font = "bold 16px sans-serif";
    for (const { pontos, pessoa } of d.poses) {
      const estado = pessoa?.estado;
      // Verde: em pé/normal. Amarelo: começando a cair (tronco inclinado, descida rápida) ou deitada ainda sem confirmar.
      // Vermelho: queda confirmada (alerta). Só muda a cor do desenho; a decisão de alertar continua sendo do detector.
      const cfg = this._cfgQueda;
      const esticando = pessoa && (pessoa.angulo >= ANGULO_ATENCAO || pessoa.velocidade >= cfg.velocidade_queda * 0.6);
      const cor = !pessoa ? "#9ca3af" : estado === "alerta" ? "#ef4444" : estado !== "normal" || esticando ? "#f59e0b" : "#22c55e";
      ctx.strokeStyle = cor;
      ctx.fillStyle = cor;
      for (const [a, b] of LIGACOES) {
        if (pontos[a][2] < 0.3 || pontos[b][2] < 0.3) continue;
        ctx.beginPath();
        ctx.moveTo(px(pontos[a][0]), pontos[a][1] * ey);
        ctx.lineTo(px(pontos[b][0]), pontos[b][1] * ey);
        ctx.stroke();
      }
      for (const i of [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]) {
        if (pontos[i][2] < 0.3) continue;
        ctx.beginPath();
        ctx.arc(px(pontos[i][0]), pontos[i][1] * ey, 4, 0, 2 * Math.PI);
        ctx.fill();
      }
      const ancora = [pontos[0], pontos[11], pontos[12]].find((p) => p[2] >= 0.3) ?? pontos[0];
      const texto = pessoa ? `ID${pessoa.id} ${estado.toUpperCase()} ${Math.round(pessoa.angulo)}°` : "TRONCO INCOMPLETO";
      ctx.lineWidth = 4;
      ctx.strokeStyle = "rgba(0,0,0,0.75)"; // contorno escuro para o texto ler em qualquer fundo
      ctx.strokeText(texto, Math.max(4, px(ancora[0]) - 20), Math.max(16, ancora[1] * ey - 14));
      ctx.fillText(texto, Math.max(4, px(ancora[0]) - 20), Math.max(16, ancora[1] * ey - 14));
    }
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
        pessoas: Math.min(100, this.estado.achadas), // todas as pessoas vistas; só as de tronco inteiro são avaliadas para queda
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
    this._desenho = null;
    this._canvasDeteccao = null;
    this._custoMedio = 0;
    this._amostras = 0;
    this._fila = null; // alertas não enviados continuam guardados no aparelho e saem na próxima vez
    this._ultimoTempoVideo = -1;
    try {
      await this._wakeLock?.release();
    } catch {
      /* já liberado */
    }
    this._wakeLock = null;
    if (this._agente && this._aparelho) {
      try {
        await api.encerrarAgenteNavegador(this._aparelho); // a chave não fica valendo depois de parar
      } catch {
        /* sem rede: a chave só existia nesta página */
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
    desenharSobreposicao: (ctx, largura, altura, espelhar) => controladorCamera.desenharSobreposicao(ctx, largura, altura, espelhar),
  };
}
