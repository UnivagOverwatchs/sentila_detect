/*
 * filaAlertas.js - Fila de alertas da câmera do navegador: NENHUM alerta de queda pode se perder por falha de rede.
 *
 * Por que existe (antes): a câmera reenviava os alertas a cada passo da detecção (~200 ms) e desistia depois de
 * 6 tentativas. Um soluço de rede de 1 a 2 segundos bastava para a queda nunca chegar ao painel. E a detecção
 * ficava parada esperando o reenvio.
 *
 * Agora:
 *   - Quem envia é um laço separado (`processar`), chamado de tempos em tempos: a detecção nunca espera a rede.
 *   - Rede fora / tempo esgotado / 5xx / 429: tenta de novo com espera crescente POR TEMPO (2 s, 4 s, 8 s... até 60 s),
 *     sem limite de tentativas. Só desiste de um alerta com mais de 24 h (já não ajuda ninguém).
 *   - Recusado (4xx) COM foto: tenta de novo SEM a foto (a foto não pode derrubar o alerta).
 *   - Recusado mesmo sem foto: sai da fila (repetir não muda nada) e é avisado no console.
 *   - 401 (chave revogada): o erro sobe para quem chamou parar a câmera; o alerta CONTINUA na fila.
 *   - A fila fica guardada no aparelho (localStorage): recarregar a página ou fechar sem querer não perde alertas.
 *
 * Sem dependência do navegador: `enviar`, `armazenamento` e `agora` são injetados (testável no Node).
 */

const UM_DIA_MS = 24 * 60 * 60 * 1000;

export class FilaAlertas {
  constructor({
    enviar, // async (corpo) => void; lança erro com .status (HTTP) ou sem status (rede)
    armazenamento = null, // { getItem, setItem } (localStorage) ou null
    agora = () => Date.now(),
    chave = "sentinela.filaAlertas",
    esperaInicialMs = 2000,
    esperaMaxMs = 60000,
    validadeMs = UM_DIA_MS,
    maxItens = 30,
  }) {
    Object.assign(this, { enviar, armazenamento, agora, chave, esperaInicialMs, esperaMaxMs, validadeMs, maxItens });
    this.itens = [];
    this._processando = false;
    this.carregar();
  }

  get tamanho() {
    return this.itens.length;
  }

  carregar() {
    try {
      const salvo = JSON.parse(this.armazenamento?.getItem(this.chave) ?? "[]");
      // Ao abrir a página de novo, os alertas guardados tentam na hora (a rede pode ter voltado).
      const agora = this.agora();
      if (Array.isArray(salvo)) {
        this.itens = salvo.filter((i) => i && i.corpo).map((i) => ({ ...i, proximaEm: agora, esperaMs: this.esperaInicialMs }));
      }
    } catch {
      this.itens = [];
    }
  }

  _salvar() {
    if (!this.armazenamento) return;
    try {
      this.armazenamento.setItem(this.chave, JSON.stringify(this.itens));
    } catch {
      // Sem espaço: guarda os alertas sem as fotos (o alerta importa mais que a foto).
      try {
        const semFotos = this.itens.map((i) => ({ ...i, corpo: { ...i.corpo, imagem_jpeg_b64: null } }));
        this.armazenamento.setItem(this.chave, JSON.stringify(semFotos));
      } catch {
        /* armazenamento indisponível (aba anônima): a fila fica só na memória */
      }
    }
  }

  adicionar(corpo) {
    const agora = this.agora();
    this.itens.push({ corpo, criadoEm: agora, proximaEm: agora, esperaMs: this.esperaInicialMs, tentativas: 0 });
    // Limite de segurança: se a rede ficar fora por muito tempo, os mais antigos perdem a foto primeiro.
    if (this.itens.length > this.maxItens) {
      for (const item of this.itens.slice(0, this.itens.length - this.maxItens)) item.corpo.imagem_jpeg_b64 = null;
    }
    this._salvar();
  }

  /** Tenta enviar os itens cujo horário chegou. Devolve quantos foram enviados. 401 é relançado (chave revogada). */
  async processar() {
    if (this._processando) return 0; // nunca dois envios do mesmo alerta ao mesmo tempo
    this._processando = true;
    let enviados = 0;
    try {
      for (const item of [...this.itens]) {
        const agora = this.agora();
        if (agora - item.criadoEm > this.validadeMs) {
          this._remover(item, "alerta com mais de 24 h descartado");
          continue;
        }
        if (item.proximaEm > agora) continue;
        item.tentativas += 1;
        try {
          await this.enviar(item.corpo);
          this._remover(item);
          enviados += 1;
        } catch (erro) {
          const status = erro?.status;
          if (status === 401) {
            this._salvar();
            throw erro; // chave revogada: para a câmera, mas o alerta fica guardado
          }
          const definitivo = status >= 400 && status < 500 && status !== 408 && status !== 429;
          if (definitivo && item.corpo.imagem_jpeg_b64) {
            item.corpo = { ...item.corpo, imagem_jpeg_b64: null }; // tenta já, sem a foto
            item.proximaEm = agora;
          } else if (definitivo) {
            this._remover(item, `painel recusou o alerta (${status})`);
          } else {
            item.proximaEm = agora + item.esperaMs; // rede/servidor: espera crescente por TEMPO
            item.esperaMs = Math.min(item.esperaMs * 2, this.esperaMaxMs);
          }
          this._salvar();
        }
      }
    } finally {
      this._processando = false;
    }
    return enviados;
  }

  _remover(item, motivo = "") {
    this.itens = this.itens.filter((i) => i !== item);
    if (motivo) console.warn(`[Sentinela] ${motivo}`);
    this._salvar();
  }
}
