/*
 * armazenamento.js - Pequenas preferências e cache offline no navegador.
 *
 * - Nome do cuidador: registrado em "tratado_por" ao resolver um alerta.
 * - Últimos alertas: mostrados quando a API está fora do ar (RF15, uso offline).
 *
 * localStorage pode falhar (aba anônima, armazenamento bloqueado), por isso
 * todo acesso fica em try/catch e o app funciona mesmo sem ele.
 */

const CHAVE_NOME = "sentinela.nomeCuidador";
const CHAVE_ALERTAS = "sentinela.ultimosAlertas";

function ler(chave, padrao) {
  try {
    const valor = localStorage.getItem(chave);
    return valor === null ? padrao : JSON.parse(valor);
  } catch {
    return padrao;
  }
}

function gravar(chave, valor) {
  try {
    localStorage.setItem(chave, JSON.stringify(valor));
  } catch {
    /* sem armazenamento disponível: segue sem cache */
  }
}

export const armazenamento = {
  nomeCuidador: () => ler(CHAVE_NOME, "Cuidador"),
  salvarNomeCuidador: (nome) => gravar(CHAVE_NOME, nome),
  ultimosAlertas: () => ler(CHAVE_ALERTAS, []),
  salvarUltimosAlertas: (alertas) => gravar(CHAVE_ALERTAS, alertas.slice(0, 30)),
};
