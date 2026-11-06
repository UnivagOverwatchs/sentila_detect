/*
 * App.jsx - Componente raiz da PWA do Sentinela.
 *
 * LÓGICA GERAL
 * ------------
 * 1. Carrega da API: alertas, câmeras, contatos e sensibilidade.
 * 2. Abre o WebSocket (useTempoReal): recebe o status a cada 1 s e os alertas na hora.
 * 3. Alerta novo -> entra na fila e abre a TELA CHEIA vermelha + som + vibração + notificação.
 * 4. Tratar alerta (Resolver/Falso alarme) -> PATCH na API, sai da fila, lista atualiza.
 * 5. Navegação por hash (#/painel, #/historico, #/config): funciona offline e
 *    sem configurar rotas no servidor.
 * 6. Sem conexão: mostra os últimos alertas salvos no aparelho (RF15).
 */
import { useCallback, useEffect, useState } from "react";
import { Layout } from "./components/Layout.jsx";
import { AlertaTelaCheia } from "./components/AlertaTelaCheia.jsx";
import { Painel } from "./pages/Painel.jsx";
import { Historico } from "./pages/Historico.jsx";
import { Configuracoes } from "./pages/Configuracoes.jsx";
import { useTempoReal } from "./hooks/useTempoReal.js";
import { api } from "./services/api.js";
import { armazenamento } from "./services/armazenamento.js";
import { avisarAlerta, liberarAudio } from "./services/aviso.js";

const TITULOS = {
  painel: ["Painel de monitoramento", "Visão em tempo real dos ambientes"],
  historico: ["Histórico de alertas", "Eventos detectados e seu status"],
  config: ["Configurações", "Sensibilidade, câmeras e contatos de emergência"],
};

function paginaDoHash() {
  const id = location.hash.replace("#/", "");
  return TITULOS[id] ? id : "painel";
}

export default function App() {
  const [pagina, setPagina] = useState(paginaDoHash);
  const [alertas, setAlertas] = useState(armazenamento.ultimosAlertas);
  const [cameras, setCameras] = useState([]);
  const [contatos, setContatos] = useState([]);
  const [sensibilidade, setSensibilidade] = useState(null);
  const [nomeCuidador, setNomeCuidador] = useState(armazenamento.nomeCuidador);
  const [fila, setFila] = useState([]); // alertas recebidos ao vivo e ainda pendentes
  const [offline, setOffline] = useState(false);

  // ------------------------------------------------------------ dados
  const carregarAlertas = useCallback(async () => {
    try {
      const lista = await api.alertas({ limite: 100 });
      setAlertas(lista);
      armazenamento.salvarUltimosAlertas(lista);
      setOffline(false);
    } catch {
      setOffline(true); // mantém os alertas do cache local
    }
  }, []);

  const carregarTudo = useCallback(async () => {
    await carregarAlertas();
    try {
      const [cams, conts, conf] = await Promise.all([api.cameras(), api.contatos(), api.configuracao()]);
      setCameras(cams);
      setContatos(conts);
      setSensibilidade(conf.sensibilidade);
    } catch {
      /* offline: telas mostram o que já tinham */
    }
  }, [carregarAlertas]);

  useEffect(() => {
    carregarTudo();
  }, [carregarTudo]);

  // ------------------------------------------------------------ tempo real
  const aoReceberAlerta = useCallback((alerta) => {
    setAlertas((atual) => {
      const nova = [alerta, ...atual.filter((a) => a.id !== alerta.id)];
      armazenamento.salvarUltimosAlertas(nova);
      return nova;
    });
    setFila((atual) => [...atual, alerta]);
    avisarAlerta(alerta);
  }, []);

  const { status, conectado } = useTempoReal(aoReceberAlerta);

  // Ao reconectar (servidor reiniciado, Wi-Fi voltou), recarrega tudo.
  useEffect(() => {
    if (conectado) carregarTudo();
  }, [conectado, carregarTudo]);

  // ------------------------------------------------------------ navegação
  useEffect(() => {
    const aoMudarHash = () => setPagina(paginaDoHash());
    window.addEventListener("hashchange", aoMudarHash);
    // Áudio só é liberado após interação: aproveitamos o primeiro clique.
    window.addEventListener("pointerdown", liberarAudio, { once: true });
    return () => window.removeEventListener("hashchange", aoMudarHash);
  }, []);

  const irPara = (id) => {
    location.hash = `#/${id}`;
  };

  // ------------------------------------------------------------ ações
  async function tratarAlerta(alerta, statusNovo) {
    const atualizado = await api.tratarAlerta(alerta.id, statusNovo, nomeCuidador);
    setAlertas((atual) => atual.map((a) => (a.id === atualizado.id ? atualizado : a)));
    setFila((atual) => atual.filter((a) => a.id !== alerta.id));
  }

  async function salvarSensibilidade(valor) {
    const resposta = await api.salvarConfiguracao(valor);
    setSensibilidade(resposta.sensibilidade);
  }

  async function alternarCamera(camera) {
    const atualizada = await api.atualizarCamera(camera.id, { ativa: !camera.ativa });
    setCameras((atual) => atual.map((c) => (c.id === atualizada.id ? atualizada : c)));
  }

  async function criarContato(contato) {
    const criado = await api.criarContato(contato);
    setContatos((atual) => [...atual, criado]);
  }

  async function removerContato(contato) {
    await api.removerContato(contato.id);
    setContatos((atual) => atual.filter((c) => c.id !== contato.id));
  }

  function salvarNome(nome) {
    setNomeCuidador(nome);
    armazenamento.salvarNomeCuidador(nome);
  }

  // ------------------------------------------------------------ render
  // Prioridade: sem conexão com o servidor > câmera parada/erro > estado da detecção.
  const cameraParada = status && status.camera_ativa && (status.erro || !status.camera_online);
  const estado = !conectado ? "offline" : cameraParada ? "camera" : status?.estado ?? "normal";
  const alertaAberto = fila[0];
  const [titulo, subtitulo] = TITULOS[pagina];

  return (
    <>
      <Layout
        pagina={pagina}
        irPara={irPara}
        titulo={titulo}
        subtitulo={subtitulo}
        estado={estado}
        cameras={cameras}
        nomeCuidador={nomeCuidador}
      >
        {pagina === "painel" && (
          <Painel
            status={status}
            conectado={conectado}
            camera={cameras.find((c) => c.id === status?.camera_id)}
            alertas={alertas}
            aoTratar={tratarAlerta}
          />
        )}
        {pagina === "historico" && <Historico alertas={alertas} aoTratar={tratarAlerta} offline={offline} />}
        {pagina === "config" && (
          <Configuracoes
            sensibilidade={sensibilidade}
            aoSalvarSensibilidade={salvarSensibilidade}
            cameras={cameras}
            aoAlternarCamera={alternarCamera}
            contatos={contatos}
            aoCriarContato={criarContato}
            aoRemoverContato={removerContato}
            nomeCuidador={nomeCuidador}
            aoSalvarNome={salvarNome}
          />
        )}
      </Layout>

      {alertaAberto && (
        <AlertaTelaCheia
          alerta={alertaAberto}
          contatoEmergencia={contatos[0]}
          aoTratar={tratarAlerta}
          totalPendentes={fila.length}
        />
      )}
    </>
  );
}
