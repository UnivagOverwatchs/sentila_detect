/*
 * App.jsx - Componente raiz da PWA do Sentinela.
 *
 * LÓGICA GERAL
 * ------------
 * 1. Carrega da API: alertas, câmeras, contatos e sensibilidade.
 * 2. Abre o WebSocket (useTempoReal): recebe o status a cada 1 s e os alertas na hora.
 * 3. Alerta novo -> entra na fila e abre a TELA CHEIA vermelha + som + vibração + notificação.
 * 4. Tratar alerta (Resolver/Falso alarme) -> PATCH na API, sai da fila, lista atualiza.
 * 5. Navegação por hash (#/painel, #/monitor, #/historico, #/cameras, #/config): funciona offline e
 *    sem configurar rotas no servidor.
 * 6. Sem conexão: mostra os últimos alertas salvos no aparelho (RF15).
 */
import { useCallback, useEffect, useState } from "react";
import { Layout } from "./components/Layout.jsx";
import { AlertaTelaCheia } from "./components/AlertaTelaCheia.jsx";
import { Painel } from "./pages/Painel.jsx";
import { Historico } from "./pages/Historico.jsx";
import { Cameras } from "./pages/Cameras.jsx";
import { Monitor } from "./pages/Monitor.jsx";
import { Configuracoes } from "./pages/Configuracoes.jsx";
import { Login } from "./pages/Login.jsx";
import { useTempoReal } from "./hooks/useTempoReal.js";
import { useCameraDoNavegador } from "./services/cameraNavegador.js";
import { api } from "./services/api.js";
import { armazenamento } from "./services/armazenamento.js";
import { avisarAlerta, liberarAudio } from "./services/aviso.js";

const TITULOS = {
  painel: ["Painel de monitoramento", "Visão em tempo real dos ambientes"],
  monitor: ["Monitor", "Os idosos estão bem? Tela para deixar aberta na TV"],
  historico: ["Histórico de alertas", "Eventos detectados e seu status"],
  cameras: ["Câmeras", "Adicionar, editar e acompanhar as câmeras"],
  config: ["Configurações", "Sensibilidade, contatos, usuários e aparelhos"],
};

function paginaDoHash() {
  const id = location.hash.replace("#/", "");
  return TITULOS[id] ? id : "painel";
}

function Aplicativo({ usuario, loginObrigatorio, aoSair }) {
  const [pagina, setPagina] = useState(paginaDoHash);
  const [alertas, setAlertas] = useState(armazenamento.ultimosAlertas);
  const [cameras, setCameras] = useState([]);
  const cameraDoAparelho = useCameraDoNavegador(); // a câmera deste aparelho continua ligada ao trocar de tela
  // Qual câmera aparece grande e se o painel mostra uma só ou todas (lembrado neste aparelho).
  const [cameraId, setCameraId] = useState(() => {
    try {
      const salvo = localStorage.getItem("sentinela.camera");
      return salvo ? Number(salvo) : null;
    } catch {
      return null;
    }
  });
  const [modoVideo, setModoVideo] = useState(() => {
    try {
      return localStorage.getItem("sentinela.modoVideo") === "grade" ? "grade" : "uma";
    } catch {
      return "uma";
    }
  });

  function selecionarCamera(id) {
    setCameraId(id);
    setModoVideo("uma");
    try {
      localStorage.setItem("sentinela.camera", String(id));
      localStorage.setItem("sentinela.modoVideo", "uma");
    } catch {
      /* sem armazenamento: vale só nesta sessão */
    }
    location.hash = "#/painel";
  }

  function mudarModoVideo(modo) {
    setModoVideo(modo);
    try {
      localStorage.setItem("sentinela.modoVideo", modo);
    } catch {
      /* idem */
    }
  }
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

  // Câmera nova (agente ou navegador acabou de conectar): o tempo real já a lista, mas o cadastro ainda não.
  // Recarrega as câmeras para ela aparecer na lista, na barra lateral e no painel sem precisar atualizar a página.
  const totalNoTempoReal = status?.cameras?.length ?? 0;
  useEffect(() => {
    if (totalNoTempoReal > cameras.length) {
      api.cameras().then(setCameras).catch(() => {});
    }
  }, [totalNoTempoReal, cameras.length]);

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

  // Edição no próprio cartão da câmera (nome e local). Erro sobe para o cartão mostrar a mensagem.
  async function salvarCamera(camera, dados) {
    const atualizada = await api.atualizarCamera(camera.id, dados);
    setCameras((atual) => atual.map((c) => (c.id === atualizada.id ? atualizada : c)));
  }

  async function excluirCamera(camera) {
    const ok = window.confirm(
      `Excluir a câmera "${camera.nome}"?\n\nIsso apaga também TODOS os alertas e fotos dela e não dá para desfazer.\n` +
        "Se um agente ainda estiver ligado a ela, feche o agente ou revogue o computador em 'Computadores com agente'; senão a câmera volta sozinha.\n" +
        "Para só parar de monitorar, use o interruptor.",
    );
    if (!ok) return;
    await api.excluirCamera(camera.id);
    setCameras((atual) => atual.filter((c) => c.id !== camera.id));
    carregarAlertas();
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
  const admin = !usuario || usuario.papel === "ADMIN"; // sem login (uso local) tudo fica liberado
  const nomeExibido = usuario?.nome ?? nomeCuidador;
  const rotuloPapel = usuario ? (usuario.papel === "ADMIN" ? "Administrador" : "Cuidador") : "Cuidador responsável";
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
        aoSelecionarCamera={selecionarCamera}
        nomeCuidador={nomeExibido}
        rotuloPapel={rotuloPapel}
        aoSair={loginObrigatorio ? aoSair : undefined}
      >
        {pagina === "painel" && (
          <Painel
            status={status}
            conectado={conectado}
            cameras={cameras}
            cameraId={cameraId}
            aoSelecionarCamera={(id) => {
              setCameraId(id);
              try {
                localStorage.setItem("sentinela.camera", String(id));
              } catch {
                /* idem */
              }
            }}
            modo={modoVideo}
            aoMudarModo={mudarModoVideo}
            alertas={alertas}
            aoTratar={tratarAlerta}
            cameraDoAparelho={cameraDoAparelho}
          />
        )}
        {pagina === "monitor" && (
          <Monitor cameras={cameras} estadoCameras={status?.cameras} alertas={alertas} aoTratar={tratarAlerta} conectado={conectado} />
        )}
        {pagina === "historico" && <Historico alertas={alertas} aoTratar={tratarAlerta} offline={offline} />}
        {pagina === "cameras" && (
          <Cameras
            cameras={cameras}
            estadoCameras={status?.cameras}
            cameraDoAparelho={cameraDoAparelho}
            admin={admin}
            aoSalvarCamera={salvarCamera}
            aoAlternarCamera={alternarCamera}
            aoExcluirCamera={excluirCamera}
            aoAtualizarCamera={(c) => setCameras((atual) => atual.map((x) => (x.id === c.id ? c : x)))}
          />
        )}
        {pagina === "config" && (
          <Configuracoes
            sensibilidade={sensibilidade}
            aoSalvarSensibilidade={salvarSensibilidade}
            contatos={contatos}
            aoCriarContato={criarContato}
            aoRemoverContato={removerContato}
            nomeCuidador={nomeCuidador}
            aoSalvarNome={salvarNome}
            admin={admin}
            usuarioLogado={usuario}
          />
        )}
      </Layout>

      {(cameraDoAparelho.fase === "transmitindo" || cameraDoAparelho.fase === "conectando") && (
        <div className="banner-camera" role="status">
          <span>
            Câmera deste aparelho ligada: <strong>{cameraDoAparelho.nome}</strong>
            {cameraDoAparelho.assistindo ? " · alguém está assistindo" : ""}
            {cameraDoAparelho.deteccao === "ativa" && " · detectando queda"}
            {cameraDoAparelho.deteccao === "carregando" && " · carregando a detecção…"}
            {cameraDoAparelho.deteccao === "indisponivel" && " · SEM detecção de queda (só vídeo)"}
          </span>
          <button type="button" className="botao botao--pequeno" onClick={cameraDoAparelho.parar}>
            Parar
          </button>
        </div>
      )}

      {/* Na tela Monitor o próprio quadro da câmera fica vermelho (som e notificação continuam). */}
      {alertaAberto && pagina !== "monitor" && (
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

/** Porteiro: pergunta ao servidor se o login é exigido e mostra a tela de entrada quando preciso. */
export default function App() {
  const [acesso, setAcesso] = useState({ fase: "verificando", usuario: null, loginObrigatorio: false });

  useEffect(() => {
    api
      .eu()
      .then((r) =>
        setAcesso({ fase: r.login_obrigatorio && !r.usuario ? "login" : "ok", usuario: r.usuario, loginObrigatorio: r.login_obrigatorio })
      )
      // Servidor fora do ar: abre o app mesmo assim (ele mostra "Sem conexão" e os últimos alertas salvos).
      .catch(() => setAcesso({ fase: "ok", usuario: null, loginObrigatorio: false }));
  }, []);

  useEffect(() => {
    const expirou = () => setAcesso({ fase: "login", usuario: null, loginObrigatorio: true });
    window.addEventListener("sentinela:sessao-expirada", expirou);
    return () => window.removeEventListener("sentinela:sessao-expirada", expirou);
  }, []);

  async function sair() {
    try {
      await api.logout();
    } finally {
      setAcesso({ fase: "login", usuario: null, loginObrigatorio: true });
    }
  }

  if (acesso.fase === "verificando") return null;
  if (acesso.fase === "login") {
    return <Login aoEntrar={(usuario) => setAcesso({ fase: "ok", usuario, loginObrigatorio: true })} />;
  }
  return <Aplicativo usuario={acesso.usuario} loginObrigatorio={acesso.loginObrigatorio} aoSair={sair} />;
}
