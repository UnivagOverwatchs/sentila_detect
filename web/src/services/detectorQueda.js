/*
 * detectorQueda.js - Lógica de queda no navegador. É a tradução FIEL de sentinela_pose/fall_detector.py
 * (mesmos limiares, mesma máquina de estados). Os testes em web/tests comparam as duas versões com vetores
 * gerados pelo Python (tests/gerar_vetores_queda.py), para uma não se afastar da outra.
 *
 * Entrada: poses = lista de pessoas; cada pessoa = 33 pontos [x_pixel, y_pixel, visibilidade 0..1] (y cresce para baixo).
 * Saída de processar(): { pessoas: [{id, estado, angulo, velocidade, temPose}], alertas: [{id, tipo, timestamp, angulo}] }
 * Tempo em segundos.
 */

export const OMBRO_E = 11;
export const OMBRO_D = 12;
export const QUADRIL_E = 23;
export const QUADRIL_D = 24;

export const ESTADO = { NORMAL: "normal", CAINDO: "caindo", NO_CHAO: "no_chao", ALERTA: "alerta" };

/** Mesmos padrões de ConfigQueda (sentinela_pose/config.py). */
export function configPadrao() {
  return {
    angulo_deitado: 60.0,
    angulo_em_pe: 35.0,
    velocidade_queda: 1.2,
    janela_velocidade: 0.5,
    desnivel_queda_lenta: 0.7,
    janela_queda_lenta: 5.0,
    janela_impacto: 2.0,
    tempo_confirma_queda: 2.0,
    tempo_no_chao: 8.0,
    tempo_recuperacao: 1.5,
    tolerancia_falha: 1.0,
    tempo_perda_max: 10.0,
    visibilidade_tronco: 0.6,
    angulo_max_valido: 135.0,
    tronco_min_px: 20.0,
    idade_minima_track: 1.0,
    janela_suavizacao: 0.3,
    margem_saida: 0.08,
    distancia_max_rastreio: 0.15,
  };
}

/** Igual a sentinela_api/sensibilidade.py: interpolação linear entre "menos alertas" (0) e "mais alertas" (1). */
const FAIXAS = {
  angulo_deitado: [70.0, 50.0],
  velocidade_queda: [1.8, 0.8],
  tempo_confirma_queda: [3.5, 1.0],
  tempo_no_chao: [15.0, 5.0],
  desnivel_queda_lenta: [1.0, 0.5],
};

function arredondar3(v) {
  // round() do Python (meio para o par) não faz diferença aqui; Math.round basta para 3 casas.
  return Math.round(v * 1000) / 1000;
}

export function aplicarSensibilidade(cfg, sensibilidade) {
  const s = Math.min(Math.max(Number(sensibilidade), 0), 1);
  for (const [nome, [minimo, maximo]] of Object.entries(FAIXAS)) cfg[nome] = arredondar3(minimo + (maximo - minimo) * s);
  return cfg;
}

// ---------------------------------------------------------------------------------------------- geometria

function dentro(p, limites) {
  if (!limites) return true;
  return p[0] >= 0 && p[0] < limites[0] && p[1] >= 0 && p[1] < limites[1];
}

function mediaPontos(pontos, a, b, visMin, limites) {
  const vis = [pontos[a], pontos[b]].filter((p) => p[2] >= visMin && dentro(p, limites));
  if (!vis.length) return null;
  return [vis.reduce((s, p) => s + p[0], 0) / vis.length, vis.reduce((s, p) => s + p[1], 0) / vis.length];
}

/** Devolve { angulo, quadril:[x,y], tronco } ou null se ombros/quadris não estão visíveis dentro da imagem. */
export function extrairMedidas(pontos, visMin = 0.3, limites = null) {
  const ombro = mediaPontos(pontos, OMBRO_E, OMBRO_D, visMin, limites);
  const quadril = mediaPontos(pontos, QUADRIL_E, QUADRIL_D, visMin, limites);
  if (!ombro || !quadril) return null;
  const dx = ombro[0] - quadril[0];
  const dy = ombro[1] - quadril[1];
  const tronco = Math.hypot(dx, dy);
  if (tronco < 1e-3) return null;
  const angulo = (Math.atan2(Math.abs(dx), -dy) * 180) / Math.PI;
  return { angulo, quadril, tronco };
}

export function pontoEmPoligono([x, y], poligono) {
  let dentroDele = false;
  let j = poligono.length - 1;
  for (let i = 0; i < poligono.length; i++) {
    const [xi, yi] = poligono[i];
    const [xj, yj] = poligono[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) dentroDele = !dentroDele;
    j = i;
  }
  return dentroDele;
}

function mediana(valores) {
  const o = [...valores].sort((a, b) => a - b);
  const m = o.length >> 1;
  return o.length % 2 ? o[m] : (o[m - 1] + o[m]) / 2;
}

// ---------------------------------------------------------------------------------------------- rastreador

export class RastreadorSimples {
  constructor(distanciaMaxPx) {
    this.distanciaMaxPx = distanciaMaxPx;
    this.ultima = new Map(); // id -> [x, y]
    this.proximoId = 1;
  }

  associar(medidas) {
    const ids = medidas.map(() => -1);
    const livres = new Set(this.ultima.keys());
    const pares = [];
    medidas.forEach((m, i) => {
      for (const [id, pos] of this.ultima) pares.push([Math.hypot(m.quadril[0] - pos[0], m.quadril[1] - pos[1]), i, id]);
    });
    // Mesmo desempate do Python (tuplas ordenadas): distância, depois índice, depois id.
    pares.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
    for (const [dist, i, id] of pares) {
      if (dist > this.distanciaMaxPx) break;
      if (ids[i] === -1 && livres.has(id)) {
        ids[i] = id;
        livres.delete(id);
      }
    }
    medidas.forEach((m, i) => {
      if (ids[i] === -1) ids[i] = this.proximoId++;
      this.ultima.set(ids[i], m.quadril);
    });
    return ids;
  }

  remover(id) {
    this.ultima.delete(id);
  }
}

// ---------------------------------------------------------------------------------------------- máquina de estados

export class MaquinaEstadosQueda {
  constructor(cfg) {
    this.cfg = cfg; // mesma referência: mudar a sensibilidade vale na hora
    this.estado = ESTADO.NORMAL;
    this.historico = []; // [ts, yQuadril, tronco], no máximo 300
    this.angulos = []; // [ts, angulo], no máximo 30
    this.primeiraObservacao = null;
    this.ultimoImpacto = -1e9;
    this.inicioDeitado = null;
    this.inicioEmPe = null;
    this.ultimaObservacao = -1e9;
    this.ultimaDeitado = -1e9;
    this.ultimoAngulo = 0;
    this.ultimaVelocidade = 0;
    this.ultimoQuadril = null;
  }

  _velocidadeDescida(agora) {
    const h = this.historico;
    const antigo = h.find(([ts]) => agora - ts <= this.cfg.janela_velocidade);
    if (!antigo || !h.length) return 0;
    const [ts0, y0, tronco0] = antigo;
    const [ts1, y1] = h[h.length - 1];
    const dt = ts1 - ts0;
    if (dt < 1e-3) return 0;
    return (y1 - y0) / Math.max(tronco0, 1) / dt;
  }

  _desceuDevagar(agora) {
    const janela = this.historico.filter(([ts]) => agora - ts <= this.cfg.janela_queda_lenta);
    if (janela.length < 2) return false;
    const yMaisAlto = Math.min(...janela.map((j) => j[1]));
    const escala = Math.max(...janela.map((j) => j[2]));
    return (janela[janela.length - 1][1] - yMaisAlto) / Math.max(escala, 1) >= this.cfg.desnivel_queda_lenta;
  }

  /** Devolve "queda", "pessoa_no_chao" ou null. medidas=null = pessoa não vista neste quadro. */
  atualizar(agora, medidas, naCama = false) {
    const cfg = this.cfg;
    let deitado;
    let emPe;

    if (medidas) {
      if (this.primeiraObservacao === null) this.primeiraObservacao = agora;
      this.ultimaObservacao = agora;
      this.ultimoQuadril = medidas.quadril;
      this.historico.push([agora, medidas.quadril[1], medidas.tronco]);
      if (this.historico.length > 300) this.historico.shift();
      this.angulos.push([agora, medidas.angulo]);
      if (this.angulos.length > 30) this.angulos.shift();
      this.ultimoAngulo = mediana(this.angulos.filter(([t]) => agora - t <= cfg.janela_suavizacao).map(([, a]) => a));
      this.ultimaVelocidade = this._velocidadeDescida(agora);

      if (this.ultimaVelocidade >= cfg.velocidade_queda) this.ultimoImpacto = agora;
      if (agora - this.primeiraObservacao < cfg.idade_minima_track) return null;

      if (naCama) {
        this._resetar();
        this.ultimoImpacto = -1e9;
        return null;
      }
      deitado = this.ultimoAngulo >= cfg.angulo_deitado;
      emPe = this.ultimoAngulo <= cfg.angulo_em_pe;
    } else {
      deitado = this.estado === ESTADO.CAINDO || this.estado === ESTADO.ALERTA;
      emPe = false;
    }

    if (deitado) {
      if (medidas) this.ultimaDeitado = agora;
      this.inicioEmPe = null;
      const houveDescida = agora - this.ultimoImpacto <= cfg.janela_impacto || (medidas !== null && this._desceuDevagar(agora));
      if (this.inicioDeitado === null) {
        this.inicioDeitado = agora;
        this.estado = houveDescida ? ESTADO.CAINDO : ESTADO.NO_CHAO;
      } else if (this.estado === ESTADO.NO_CHAO && houveDescida) {
        this.estado = ESTADO.CAINDO;
      }
      const tempoDeitado = agora - this.inicioDeitado;
      if (this.estado === ESTADO.CAINDO && tempoDeitado >= cfg.tempo_confirma_queda) {
        this.estado = ESTADO.ALERTA;
        return "queda";
      }
      if (this.estado === ESTADO.NO_CHAO && tempoDeitado >= cfg.tempo_no_chao) {
        this.estado = ESTADO.ALERTA;
        return "pessoa_no_chao";
      }
      return null;
    }

    if (emPe) {
      if (this.inicioEmPe === null) this.inicioEmPe = agora;
      if (agora - this.inicioEmPe >= cfg.tempo_recuperacao) this._resetar();
      return null;
    }

    if (this.inicioDeitado !== null && agora - this.ultimaDeitado > cfg.tolerancia_falha) {
      if (this.estado !== ESTADO.ALERTA) {
        this.inicioDeitado = null;
        this.estado = ESTADO.NORMAL;
      }
    }
    return null;
  }

  /** Mesmos números do Python (MaquinaEstadosQueda.detalhes): para calibrar os limiares com casos reais. */
  detalhes(agora, pessoasNaCena = 0) {
    const cfg = this.cfg;
    const r = (v, casas) => Math.round(v * 10 ** casas) / 10 ** casas;
    const limiares = {};
    for (const k of ["angulo_deitado", "angulo_em_pe", "velocidade_queda", "desnivel_queda_lenta", "tempo_confirma_queda", "tempo_no_chao"]) limiares[k] = cfg[k];
    return {
      angulo: r(this.ultimoAngulo, 1),
      velocidade: r(this.ultimaVelocidade, 3),
      tempo_deitado: this.inicioDeitado !== null ? r(agora - this.inicioDeitado, 2) : 0,
      desde_impacto: this.ultimoImpacto > -1e8 ? r(agora - this.ultimoImpacto, 2) : null,
      pessoas_na_cena: pessoasNaCena,
      limiares,
      trajetoria_angulo: this.angulos.slice(-30).map(([t, a]) => [r(t - agora, 2), r(a, 1)]),
      trajetoria_quadril: this.historico.slice(-30).map(([t, y, tr]) => [r(t - agora, 2), r(y, 1), r(tr, 1)]),
    };
  }

  _resetar() {
    this.estado = ESTADO.NORMAL;
    this.inicioDeitado = null;
    this.inicioEmPe = null;
  }
}

// ---------------------------------------------------------------------------------------------- fachada

export class DetectorQueda {
  constructor(largura, altura, cfg = configPadrao(), visMin = 0.3) {
    this.cfg = cfg;
    this.visMin = visMin;
    this.limites = [largura, altura];
    this.rastreador = new RastreadorSimples(cfg.distancia_max_rastreio * Math.hypot(largura, altura));
    this.maquinas = new Map();
    this.zonasCama = [];
  }

  /** Polígonos com coordenadas de 0 a 1 (como a tela os grava) viram pixels. */
  definirZonasCama(poligonos) {
    const [l, a] = this.limites;
    this.zonasCama = (poligonos || []).filter((p) => p.length >= 3).map((p) => p.map(([x, y]) => [x * l, y * a]));
  }

  _naCama(m) {
    return this.zonasCama.some((z) => pontoEmPoligono(m.quadril, z));
  }

  _saiuDeCena(maq) {
    if (!maq.ultimoQuadril) return false;
    const [x, y] = maq.ultimoQuadril;
    const [l, a] = this.limites;
    const m = this.cfg.margem_saida;
    return x < m * l || x > (1 - m) * l || y < m * a; // a borda de baixo não conta: quem cai perto da câmera continua no chão
  }

  processar(poses, agora) {
    const visTronco = Math.max(this.visMin, this.cfg.visibilidade_tronco);
    const validas = [];
    for (const pontos of poses) {
      const m = extrairMedidas(pontos, visTronco, this.limites);
      if (m && m.angulo <= this.cfg.angulo_max_valido && m.tronco >= this.cfg.tronco_min_px) validas.push([pontos, m]);
    }
    const ids = this.rastreador.associar(validas.map(([, m]) => m));

    const pessoas = [];
    const alertas = [];
    const vistos = new Set();

    validas.forEach(([pontos, m], k) => {
      const id = ids[k];
      vistos.add(id);
      if (!this.maquinas.has(id)) this.maquinas.set(id, new MaquinaEstadosQueda(this.cfg));
      const maq = this.maquinas.get(id);
      const tipo = maq.atualizar(agora, m, this._naCama(m));
      if (tipo) alertas.push({ id, tipo, timestamp: agora, angulo: m.angulo, detalhes: maq.detalhes(agora, validas.length) });
      pessoas.push({ id, estado: maq.estado, angulo: maq.ultimoAngulo, velocidade: maq.ultimaVelocidade, temPose: true, pontos });
    });

    for (const id of [...this.maquinas.keys()]) {
      if (vistos.has(id)) continue;
      const maq = this.maquinas.get(id);
      if ((maq.estado === ESTADO.CAINDO || maq.estado === ESTADO.NO_CHAO) && this._saiuDeCena(maq)) {
        this.maquinas.delete(id); // sumiu andando para fora da imagem: não houve queda
        this.rastreador.remover(id);
        continue;
      }
      if (agora - maq.ultimaObservacao > this.cfg.tempo_perda_max) {
        this.maquinas.delete(id);
        this.rastreador.remover(id);
        continue;
      }
      const tipo = maq.atualizar(agora, null);
      if (tipo) alertas.push({ id, tipo, timestamp: agora, angulo: maq.ultimoAngulo, detalhes: maq.detalhes(agora, validas.length) });
      if (maq.estado !== ESTADO.NORMAL) pessoas.push({ id, estado: maq.estado, angulo: maq.ultimoAngulo, velocidade: 0, temPose: false });
    }
    return { pessoas, alertas };
  }
}
