# sentinela_pose — detecção de quedas por pose (alternativa ao YOLO treinado)

## Por que mudar
| Problema no fluxo atual | Causa | Como a pose resolve |
|---|---|---|
| Pesado | `ultralytics` + `torch` CUDA (~2,5 GB) e modelo de **segmentação** | MediaPipe Pose *lite* (~3 MB), CPU, sem PyTorch |
| Não detecta | modelo treinado com 690 imagens e validado nas **mesmas** imagens do treino (métricas infladas) | modelo pré-treinado do Google em grande volume de dados |
| Falso positivo/negativo | decisão pela proporção da caixa (`altura/largura >= 1.05`), que muda com a perspectiva da câmera | ângulo do tronco (ombro↔quadril) + velocidade de descida + tempo no chão |

## Como funciona
1. `pose_estimator.py`: 33 pontos do corpo por pessoa.
2. `fall_detector.py`:
   - **ângulo do tronco**: 0° em pé, 90° deitado (mediana dos últimos 0,3 s);
   - **descida do quadril** medida em "comprimentos de tronco" (vale perto ou longe da câmera):
     - *brusca*: velocidade ≥ `QUEDA_VELOCIDADE` (1,2 tronco/s);
     - *lenta*: desceu ≥ `QUEDA_DESNIVEL_LENTA` (0,7 tronco) dentro de `QUEDA_JANELA_LENTA` (5 s);
   - **máquina de estados** por pessoa:

     | Estado | Quando |
     |---|---|
     | `NORMAL` | em pé, sentado, andando |
     | `CAINDO` | deitado depois de descida vista (brusca ou lenta) → alerta `queda` em 2 s |
     | `NO_CHAO` | deitado sem descida vista → alerta `pessoa_no_chao` em 8 s |
     | `ALERTA` | alerta disparado (uma vez por episódio); volta a `NORMAL` após 1,5 s em pé |

   - **filtros contra falso alarme**: ombros/quadril fora da imagem ou pouco visíveis, tronco invertido
     (> 135°), pessoa muito pequena, ID visto há menos de 1 s; sem pose, só continua contando se a queda foi vista.
3. `alertas.py`: salva imagem em `alertas_queda/` e envia WhatsApp (mesma API local já usada).

## Rodar
```bash
pip install -r requirements_pose.txt
python servidor.py                     # com interface web (ver README da raiz)
python main_pose.py                    # modo simples: janela do OpenCV
python main_pose.py --fonte video.mp4  # testar com vídeo de queda
python -m pytest -v                    # testes (sem câmera)
```
Na 1ª execução o modelo é baixado para `modelos/`.

## Calibração
Ajuste os limiares no `.env` (ver `.env.exemplo_pose`). Use vídeos públicos de queda
(ex.: UR Fall Detection Dataset, Le2i) com `--fonte` para medir acertos antes de ir para a ILPI.

## Limitações
- Câmera muito alta (vista de cima) reduz a variação de ângulo: prefira câmeras a 2–2,5 m em diagonal.
- Ombros e quadril precisam aparecer: pessoa cortada pela borda é ignorada de propósito.
- Cama x chão: deitar na cama devagar pode ser lido como queda lenta (próximo passo: área da cama).
- Corpo deitado e parcialmente oculto pode perder a pose; após uma queda vista, a contagem continua por até `QUEDA_TEMPO_PERDA_MAX`.
- Muitas pessoas cruzando: o rastreador é simples (vizinho mais próximo).
