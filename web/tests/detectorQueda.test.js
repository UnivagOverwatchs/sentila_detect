// Compara o detector em JavaScript com o de Python, cenário por cenário (vetores gerados por tests/gerar_vetores_queda.py).
// Rodar: node --test web/tests
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { aplicarSensibilidade, configPadrao, DetectorQueda } from "../src/services/detectorQueda.js";

const cenas = JSON.parse(readFileSync(new URL("./vetores_queda.json", import.meta.url), "utf8"));
const perto = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-6, `${msg}: ${a} != ${b}`);

for (const cena of cenas) {
  test(`cenário ${cena.nome}: mesmo resultado que o Python`, () => {
    const cfg = aplicarSensibilidade(configPadrao(), cena.sensibilidade);
    const det = new DetectorQueda(cena.largura, cena.altura, cfg, 0.3);
    det.definirZonasCama(cena.cama);
    cena.quadros.forEach((q, k) => {
      const { pessoas, alertas } = det.processar(q.poses, q.t);
      const onde = `quadro ${k} (t=${q.t})`;
      assert.equal(alertas.length, q.alertas.length, `${onde}: alertas`);
      alertas.forEach((a, i) => {
        assert.equal(a.id, q.alertas[i].id, onde);
        assert.equal(a.tipo, q.alertas[i].tipo, onde);
        perto(a.angulo, q.alertas[i].angulo, `${onde} ângulo do alerta`);
        const dp = q.alertas[i].detalhes;
        perto(a.detalhes.angulo, dp.angulo, `${onde} detalhes.angulo`);
        perto(a.detalhes.velocidade, dp.velocidade, `${onde} detalhes.velocidade`);
        perto(a.detalhes.tempo_deitado, dp.tempo_deitado, `${onde} detalhes.tempo_deitado`);
        assert.equal(a.detalhes.pessoas_na_cena, dp.pessoas_na_cena, onde);
        assert.deepEqual(a.detalhes.limiares, dp.limiares, onde);
        assert.equal(a.detalhes.trajetoria_angulo.length, dp.trajetoria_angulo.length, onde);
        assert.equal(a.detalhes.trajetoria_quadril.length, dp.trajetoria_quadril.length, onde);
      });
      assert.equal(pessoas.length, q.pessoas.length, `${onde}: pessoas`);
      pessoas.forEach((p, i) => {
        const e = q.pessoas[i];
        assert.equal(p.id, e.id, onde);
        assert.equal(p.estado, e.estado, `${onde}: estado`);
        assert.equal(p.temPose, e.temPose, onde);
        perto(p.angulo, e.angulo, `${onde} ângulo`);
        perto(p.velocidade, e.velocidade, `${onde} velocidade`);
      });
    });
  });
}

test("os cenários principais alertam como esperado", () => {
  const por = Object.fromEntries(cenas.map((c) => [c.nome, c.quadros.flatMap((q) => q.alertas.map((a) => a.tipo))]));
  assert.deepEqual(por.queda, ["queda"]);
  assert.deepEqual(por.em_pe, []);
  assert.deepEqual(por.cama, []);
  assert.deepEqual(por.invalidas, []);
  assert.ok(por.no_chao.includes("pessoa_no_chao"));
});
