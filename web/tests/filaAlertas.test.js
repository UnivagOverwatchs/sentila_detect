// Fila de alertas da câmera do navegador: nenhum alerta pode se perder por soluço de rede.
// Rodar: node --test web/tests
import test from "node:test";
import assert from "node:assert/strict";
import { FilaAlertas } from "../src/services/filaAlertas.js";

function memoria() {
  const dados = {};
  return { getItem: (k) => dados[k] ?? null, setItem: (k, v) => { dados[k] = v; }, dados };
}

function erroHttp(status) {
  const e = new Error(String(status));
  e.status = status;
  return e;
}

test("rede fora por 30 s: o alerta NÃO é descartado e sai quando a rede volta", async () => {
  let relogio = 0;
  let rede = false;
  const recebidos = [];
  const fila = new FilaAlertas({
    agora: () => relogio,
    enviar: async (corpo) => { if (!rede) throw new Error("sem rede"); recebidos.push(corpo); },
  });
  fila.adicionar({ tipo: "queda" });
  for (let s = 0; s < 30; s += 0.2) { relogio = s * 1000; await fila.processar(); } // 150 passos, como a detecção antiga
  assert.equal(fila.tamanho, 1, "o alerta continua na fila");
  rede = true;
  relogio += 61_000;
  await fila.processar();
  assert.deepEqual(recebidos, [{ tipo: "queda" }]);
  assert.equal(fila.tamanho, 0);
});

test("espera cresce por tempo: não martela o servidor a cada passo", async () => {
  let relogio = 0;
  let tentativas = 0;
  const fila = new FilaAlertas({ agora: () => relogio, enviar: async () => { tentativas += 1; throw erroHttp(503); } });
  fila.adicionar({ tipo: "queda" });
  for (let ms = 0; ms <= 10_000; ms += 200) { relogio = ms; await fila.processar(); }
  assert.ok(tentativas <= 4, `em 10 s foram ${tentativas} tentativas (antes seriam 50)`); // 0 s, 2 s, 6 s
});

test("recusado com foto: reenvia sem a foto e o alerta chega", async () => {
  const recebidos = [];
  const fila = new FilaAlertas({
    enviar: async (corpo) => { if (corpo.imagem_jpeg_b64) throw erroHttp(413); recebidos.push(corpo); },
  });
  fila.adicionar({ tipo: "queda", imagem_jpeg_b64: "AAAA" });
  await fila.processar();
  await fila.processar();
  assert.equal(recebidos.length, 1);
  assert.equal(recebidos[0].imagem_jpeg_b64, null);
});

test("401: para a câmera, mas o alerta continua guardado", async () => {
  const fila = new FilaAlertas({ enviar: async () => { throw erroHttp(401); } });
  fila.adicionar({ tipo: "queda" });
  await assert.rejects(() => fila.processar(), (e) => e.status === 401);
  assert.equal(fila.tamanho, 1);
});

test("recarregar a página não perde alertas (fila guardada no aparelho)", async () => {
  const armazenamento = memoria();
  const primeira = new FilaAlertas({ armazenamento, enviar: async () => { throw new Error("sem rede"); } });
  primeira.adicionar({ tipo: "queda", camera_id: 3 });
  await primeira.processar();
  const recebidos = [];
  const depoisDeRecarregar = new FilaAlertas({ armazenamento, enviar: async (c) => recebidos.push(c) });
  assert.equal(depoisDeRecarregar.tamanho, 1);
  await depoisDeRecarregar.processar();
  assert.deepEqual(recebidos, [{ tipo: "queda", camera_id: 3 }]);
});

test("só desiste depois de 24 h", async () => {
  let relogio = 0;
  const fila = new FilaAlertas({ agora: () => relogio, enviar: async () => { throw new Error("sem rede"); } });
  fila.adicionar({ tipo: "queda" });
  relogio = 23 * 3600 * 1000;
  await fila.processar();
  assert.equal(fila.tamanho, 1);
  relogio = 25 * 3600 * 1000;
  await fila.processar();
  assert.equal(fila.tamanho, 0);
});

test("dois processamentos ao mesmo tempo não enviam o mesmo alerta duas vezes", async () => {
  let envios = 0;
  const fila = new FilaAlertas({ enviar: async () => { envios += 1; await new Promise((r) => setTimeout(r, 20)); } });
  fila.adicionar({ tipo: "queda" });
  await Promise.all([fila.processar(), fila.processar()]);
  assert.equal(envios, 1);
});
