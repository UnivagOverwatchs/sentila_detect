/*
 * Cameras.jsx - Página "Câmeras": tudo sobre câmeras em um só lugar (antes ficava espalhado em Configurações).
 *
 * LÓGICA
 *   1. Resumo no topo: quantas câmeras, quantas online/sem sinal/desativadas, e o botão "Adicionar câmera".
 *   2. "Adicionar câmera" abre o assistente (AdicionarCamera): escolhe o tipo e recebe instruções prontas.
 *   3. Se ESTE aparelho estiver transmitindo, o controle dele aparece logo abaixo (para parar ou ver o estado).
 *   4. Lista de câmeras (CartaoCamera): estado em tempo real, ligar/desligar, editar, área da cama e excluir.
 *   5. Computadores com agente (AgentesCamera): trocar chave e revogar acesso.
 * Cuidador (não administrador) só vê a lista e o estado; as ações de cadastro são do administrador.
 */
import { useState } from "react";
import { AdicionarCamera } from "../components/AdicionarCamera.jsx";
import { AgentesCamera } from "../components/AgentesCamera.jsx";
import { CameraDoAparelho } from "../components/CameraDoAparelho.jsx";
import { CartaoCamera, situacaoDaCamera } from "../components/CartaoCamera.jsx";
import { IconeMais } from "../components/Icones.jsx";

export function Cameras({ cameras, estadoCameras = [], cameraDoAparelho, admin, aoSalvarCamera, aoAlternarCamera, aoExcluirCamera, aoAtualizarCamera }) {
  const [adicionando, setAdicionando] = useState(false);
  const [versaoAgentes, setVersaoAgentes] = useState(0); // muda quando o assistente cria um computador novo

  const estadoDe = (camera) => estadoCameras.find((e) => e.id === camera.id);
  const contagem = { online: 0, "sem-sinal": 0, desativada: 0, aguardando: 0 };
  cameras.forEach((c) => {
    contagem[situacaoDaCamera(c, estadoDe(c)).chave] += 1;
  });
  const aparelhoLigado = cameraDoAparelho && ["transmitindo", "conectando", "pedindo"].includes(cameraDoAparelho.fase);

  return (
    <div className="pilha">
      <section className="cartao resumo-cameras">
        <div className="resumo-cameras__numeros">
          <div>
            <strong>{cameras.length}</strong>
            <span>{cameras.length === 1 ? "câmera" : "câmeras"}</span>
          </div>
          <div className="resumo--ok">
            <strong>{contagem.online}</strong>
            <span>online</span>
          </div>
          <div className={contagem["sem-sinal"] ? "resumo--erro" : ""}>
            <strong>{contagem["sem-sinal"]}</strong>
            <span>sem sinal</span>
          </div>
          <div>
            <strong>{contagem.desativada}</strong>
            <span>{contagem.desativada === 1 ? "desativada" : "desativadas"}</span>
          </div>
        </div>
        {admin && !adicionando && (
          <button type="button" className="botao" onClick={() => setAdicionando(true)}>
            <IconeMais tamanho={14} /> Adicionar câmera
          </button>
        )}
      </section>

      {admin && adicionando && (
        <AdicionarCamera
          cameras={cameras}
          estadoCameras={estadoCameras}
          cameraDoAparelho={cameraDoAparelho}
          aoFechar={() => setAdicionando(false)}
          aoCriarAgente={() => setVersaoAgentes((v) => v + 1)}
        />
      )}

      {aparelhoLigado && !adicionando && <CameraDoAparelho camera={cameraDoAparelho} />}

      <section className="cartao">
        <header className="cartao__cabecalho">
          <h2>Câmeras cadastradas</h2>
          <p>O interruptor liga ou desliga o monitoramento sem apagar nada.</p>
        </header>
        {cameras.length === 0 ? (
          <p className="dica">Nenhuma câmera ainda.{admin ? " Clique em “Adicionar câmera” para começar." : ""}</p>
        ) : (
          <ul className="lista-cameras">
            {cameras.map((c) => (
              <CartaoCamera
                key={c.id}
                camera={c}
                estado={estadoDe(c)}
                admin={admin}
                aoSalvar={aoSalvarCamera}
                aoAlternar={aoAlternarCamera}
                aoExcluir={aoExcluirCamera}
                aoAtualizar={aoAtualizarCamera}
              />
            ))}
          </ul>
        )}
      </section>

      {admin && <AgentesCamera versao={versaoAgentes} />}
    </div>
  );
}
