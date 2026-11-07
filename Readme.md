# SENTINELA - Detecção de Quedas com Visão Computacional

> **Projeto Integrador** - Monitoramento de quedas de pessoas idosas em Instituições de Longa Permanência (ILPI), usando as câmeras já existentes, estimativa de pose em CPU e uma PWA para os cuidadores.

---

## Criadores

- **Hianny Urt**
- **Thalia Limeira**
- **Igor Alves**
- **Cleverson Felipe**

**Instituição:** Univag
**Data:** 2026

---

## Visão geral

```
Webcam / câmera IP (RTSP)
        │
        ▼
Serviço de Visão (Python)          sentinela_pose/  +  sentinela_api/servico_visao.py
  1. MediaPipe Pose  → 33 pontos do corpo por pessoa (CPU, sem PyTorch)
  2. Rastreador      → ID por pessoa
  3. Lógica de queda → ângulo do tronco + descida do quadril + tempo no chão
        │ grava evento/alerta + foto do momento
        ▼
Banco de dados                      PostgreSQL (servidor) ou SQLite (local)
        ▲
        │ REST + WebSocket + quadros JPEG
API FastAPI                         sentinela_api/app.py
        ▲
        │
PWA React (cuidador)                web/  → Painel, Histórico, Configurações, alerta em tela cheia
```

Por que pose em vez do YOLO treinado (abordagem anterior, no fim deste arquivo):
- **Mais leve:** MediaPipe Pose *lite* (~3 MB) roda em tempo real na CPU; não precisa de PyTorch/CUDA.
- **Mais confiável:** modelo pré-treinado pelo Google, em vez de 690 imagens validadas no próprio treino.
- **Menos afetado pela perspectiva:** decide pelo ângulo do tronco e pela descida do quadril, não pela proporção da caixa.

---

## Como a queda é identificada

| Situação | Como reconhece | Alerta |
|---|---|---|
| **Queda brusca** | quadril desce rápido (≥ 1,2 tronco/s) e a pessoa fica deitada | `queda` após **2 s** deitada |
| **Queda lenta** | quadril desce aos poucos (≥ 0,7 tronco em até 5 s) e termina deitada | `queda` após **2 s** deitada |
| **Pessoa no chão** | já aparece deitada (descida não foi vista) | `pessoa_no_chao` após **8 s** |
| Sentar / agachar | tronco continua quase vertical | nenhum |
| Levantou logo | ficou em pé por 1,5 s antes da confirmação | nenhum (volta ao normal) |

"Deitada" = tronco (linha quadril → ombro) com mais de 60° em relação à vertical. Medidas em "comprimentos de tronco" valem perto ou longe da câmera.

**Filtros contra falso alarme:**
- pose descartada se ombros/quadril estiverem fora da imagem ou pouco visíveis (pessoa cortada pela borda, sentada perto da câmera);
- quadril acima dos ombros (> 135°) é tratado como erro do modelo;
- uma pessoa precisa ser vista por 1 s antes de poder gerar alerta;
- o ângulo usado é a mediana dos últimos 0,3 s;
- se a pose some, a contagem só continua quando a queda foi vista.

Todos os limiares ficam em `sentinela_pose/config.py` e podem ser trocados pelo `.env`. Na interface, o controle **Sensibilidade** ajusta vários deles de uma vez.

---

## Estrutura do projeto

```
DetectHumans/
├── servidor.py              # sobe tudo: serviço de visão + API + PWA (uso principal)
├── main_pose.py             # modo simples: janela do OpenCV, sem interface web
├── sentinela_pose/          # detecção (não depende da interface)
│   ├── config.py            #   limiares ajustáveis
│   ├── pontos.py            #   estrutura da pose (33 pontos)
│   ├── pose_estimator.py    #   MediaPipe Pose Landmarker
│   ├── fall_detector.py     #   rastreador + máquina de estados da queda
│   └── alertas.py           #   foto do alerta + WhatsApp
├── sentinela_api/           # backend da PWA
│   ├── banco.py             #   PostgreSQL ou SQLite (mesmo esquema da documentação)
│   ├── servico_visao.py     #   detecção em thread + quadro atual + status
│   ├── sensibilidade.py     #   controle 0–100% → limiares
│   └── app.py               #   rotas REST, WebSocket e arquivos da PWA
├── web/                     # PWA em React (Vite)
├── tests/                   # testes automáticos (pytest)
├── requirements_pose.txt    # dependências Python desta versão
├── .env.exemplo_pose        # modelo de configuração
└── (arquivos da abordagem anterior: dataset*/, runs/, yolov8n.pt ...; os scripts alerta*.py foram removidos)
```

---

## Instalação

Requisitos: **Python 3.12**, **Node.js 18+** e uma webcam ou câmera IP.

```powershell
# 1. Ambiente Python
python -m venv .venv
.\.venv\Scripts\activate            # Linux/Mac: source .venv/bin/activate
pip install -r requirements_pose.txt

# 2. Interface (compilar uma vez; o servidor passa a entregá-la)
cd web
npm install
npm run build
cd ..
```

Na primeira execução o modelo de pose é baixado para `modelos/`.

> Se o `pip` instalou `opencv-python` e `opencv-contrib-python` juntos, remova os dois e reinstale só o do requirements: `pip uninstall -y opencv-python opencv-contrib-python && pip install -r requirements_pose.txt`.

---

## Como executar

```powershell
python servidor.py                                   # webcam 0 → http://localhost:8000
python servidor.py --fonte 1 --camera "Quarto" --local "1º andar"
python servidor.py --fonte rtsp://usuario:senha@ip:554/stream
python servidor.py --host 0.0.0.0                    # acessar pelo celular na mesma rede
```

- **Ctrl+C** encerra (libera a câmera; se o navegador segurar conexões, força a saída em 5 s; 2º Ctrl+C sai na hora).
- Para descobrir o número da webcam USB: rode com `--fonte 0`, `1`, `2`... ou use `listar_cameras.py`.

Modo simples, sem interface web (útil para calibrar):

```powershell
python main_pose.py --fonte 1                # janela do OpenCV com esqueleto e estado; 'q' sai
python main_pose.py --fonte video_queda.mp4  # testar com vídeo gravado
```

### Telas da PWA

| Tela | O que tem |
|---|---|
| **Painel** | vídeo ao vivo com esqueleto/estado, câmeras ativas, alertas pendentes, sensibilidade, pessoas em cena, alertas recentes |
| **Histórico** | filtro por tipo, foto do momento, *Resolver* / *Falso alarme* (registra quem tratou e quando) |
| **Configurações** | sensibilidade, liga/desliga câmeras, contatos de emergência, nome do cuidador, notificações |
| **Alerta em tela cheia** | sirene, vibração e notificação; *Ligar para…*, *Ver câmera ao vivo*, *Resolver*, *Falso alarme* |

No celular a navegação vai para a barra inferior e o app pode ser instalado na tela inicial.

---

## Configuração (`.env`)

Copie `.env.exemplo_pose` para `.env` (o `.env` não vai para o git). Tudo é opcional.

```env
# Câmera padrão do servidor.py
CAMERA_FONTE=1
CAMERA_NOME=Quarto
CAMERA_LOCAL=1º andar

# Banco PostgreSQL (sem isto, usa o arquivo local sentinela.db)
DATABASE_URL=postgresql://usuario:senha@servidor:5432/nome_do_banco
# ou: PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD / PGSSLMODE

# Web Push (gere com: python -m sentinela_api.push --gerar-chaves)
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_CONTATO=mailto:admin@example.com   # e-mail/URL válidos: a Apple recusa (403) se for inválido, ex. ".local"

# Login (servidor público): 1 = exige usuário e senha em toda a API, no vídeo, nas fotos e no tempo real
LOGIN_OBRIGATORIO=0
# COOKIE_SEGURO=1   # padrão 1 quando o login é obrigatório (cookie só trafega por HTTPS ou localhost)

# WhatsApp: serviço sentinela_whatsapp (pode estar em outro servidor).
# O Sentinela avisa o notificador assim que grava um alerta; ele envia para os contatos de emergência.
NOTIFICADOR_URL=http://ip-do-servidor-whatsapp:8100
NOTIFICADOR_TOKEN=mesmo valor de NOTIF_TOKEN no notificador

# Envio antigo (um número fixo, mesma máquina) — deixe vazio quando usar o notificador

WHATSAPP_URL=http://localhost:3000/client/sendMessage/ABCD
WHATSAPP_CHAT_ID=55DDDNUMERO@c.us
ALERTA_COOLDOWN=30

# Modelo de pose: lite (rápido) | full | heavy (preciso)
POSE_MODELO=lite

# Limiares (exemplos; lista completa em sentinela_pose/config.py)
QUEDA_ANGULO_DEITADO=60
QUEDA_VELOCIDADE=1.2
QUEDA_DESNIVEL_LENTA=0.7
QUEDA_TEMPO_CONFIRMA=2
QUEDA_TEMPO_NO_CHAO=8
```

---

## Banco de dados

O servidor mostra ao iniciar qual banco está em uso (`PostgreSQL (servidor/banco)` ou `SQLite (sentinela.db)`) e cria as tabelas que faltarem, sem alterar as existentes. Tabelas, seguindo o modelo lógico da documentação:

| Tabela | Conteúdo |
|---|---|
| `camera` | nome, local, fonte, ativa |
| `evento` | câmera, ID da pessoa, tipo (`QUEDA` / `MOVIMENTO_ANOMALO`), confiança, data/hora, caminho da foto |
| `alerta` | status (`PENDENTE` / `RESOLVIDO` / `FALSO_ALARME`), quem tratou, quando |
| `contato_emergencia` | nome, telefone, tipo |
| `configuracao` | sensibilidade |

LGPD: nenhum vídeo é gravado; só a foto do momento do alerta (pasta `alertas_queda/`).

---

## API

| Método | Rota | Função |
|---|---|---|
| GET | `/api/status` | estado geral, FPS, pessoas, pendentes |
| GET | `/api/quadro` | quadro atual da câmera (JPEG) |
| GET | `/api/video` | vídeo MJPEG contínuo (para VLC e afins) |
| GET | `/api/alertas?status=&tipo=&limite=` | lista de alertas |
| PATCH | `/api/alertas/{id}` | resolver / falso alarme |
| GET | `/api/alertas/{id}/imagem` | foto do momento |
| GET / PUT | `/api/cameras`, `/api/cameras/{id}` | listar, ligar/desligar |
| GET / PUT | `/api/configuracao` | sensibilidade |
| GET / POST / DELETE | `/api/contatos`, `/api/contatos/{id}` | contatos de emergência |
| WS | `/api/ws` | status a cada 1 s + alertas novos na hora |

Documentação interativa: `http://localhost:8000/docs`.

---

## Testes

```powershell
python -m pytest -v
```

31 testes, sem câmera nem MediaPipe (poses sintéticas e captura simulada):
- lógica de queda: brusca, lenta, deitado sem descida, sentar, levantar, perda da pose, duas pessoas, falsos alarmes reais (quadril fora da imagem, tronco invertido, IDs que piscam);
- API: alerta gerado pela queda simulada, tratar alerta, filtros, sensibilidade, câmeras, contatos, WebSocket, quadro JPEG.

Os testes sempre usam um SQLite temporário, nunca o banco do servidor.

---

## Calibração e limitações

- **Posição da câmera:** no alto do canto do quarto (2–2,5 m), em diagonal. Câmera na altura da mesa ou olhando de cima reduz a precisão do ângulo.
- **Corpo inteiro:** ombros e quadril precisam aparecer; pessoa cortada pela borda é ignorada de propósito.
- **Cama x chão:** em *Configurações → Câmeras → Marcar cama* o administrador clica nos cantos da cama sobre a imagem da câmera (até 4 zonas). Enquanto o quadril estiver dentro da zona, deitar não gera alerta; fora dela a detecção é a de sempre. A zona aparece sombreada no vídeo. Quem sai da cama e deita no chão alerta normalmente. Sem zona marcada, o comportamento é o antigo.
- **Login:** com `LOGIN_OBRIGATORIO=1` todo acesso à API, ao vídeo, às fotos e ao tempo real exige usuário e senha (sessão em cookie HttpOnly, senha com scrypt, bloqueio de 15 min após 5 erros seguidos). O primeiro administrador nasce pela linha de comando: `python -m sentinela_api.usuarios criar --usuario admin --nome Administrador --papel ADMIN` (a senha é pedida no terminal). Depois o administrador cria os demais em *Configurações → Usuários*. Papéis: **ADMIN** altera configurações, câmeras, contatos, usuários e aparelhos; **CUIDADOR** acompanha o painel e trata alertas. Sem `LOGIN_OBRIGATORIO`, o painel continua aberto (uso local); use `--host 0.0.0.0` só em rede interna confiável.
- **Agente de visão (`agente.py`):** roda onde a câmera é alcançável (ex.: computador pequeno no local), detecta quedas e envia ao painel, por HTTPS e com chave própria, o alerta, a foto e um quadro por segundo para o vídeo ao vivo. Se a rede cair, os alertas esperam em `fila_agente/`. O push e o WhatsApp saem do painel. Chaves: `python -m sentinela_api.agentes criar --nome ...`. Passo a passo em [deploy/IMPLANTACAO.md](deploy/IMPLANTACAO.md).
- **Modo painel (servidor sem câmera, ex.: VPS):** `python servidor.py --painel` sobe só a API, a interface, o login e o push, lendo o banco que outro computador (com a câmera) alimenta. A imagem Docker e o passo a passo com Apache e HTTPS estão em [deploy/IMPLANTACAO.md](deploy/IMPLANTACAO.md). Ainda sem vídeo ao vivo nem foto dos alertas nesse modo.
- **Aparelhos e envios de push:** *Configurações → Aparelhos que recebem alertas* lista, renomeia e remove os celulares cadastrados e mostra o resultado do último aviso. Cada tentativa de envio fica na tabela `envio_push` (OK/FALHA); o envio tenta de novo uma vez em erro passageiro e remove aparelhos expirados.
- **Notificação com o app fechado:** Web Push (VAPID) implementado; exige HTTPS no celular. Gere as chaves com `python -m sentinela_api.push --gerar-chaves` e ative em *Configurações → Ativar notificações*.
- **Uma câmera por servidor** nesta versão.

## Próximas etapas

- [x] Login e perfis Cuidador/Administrador (sessão em cookie; sem JWT)
- [x] Web Push (alerta com o app fechado) — falta testar em celular com HTTPS
- [ ] Várias câmeras no mesmo servidor
- [x] Área da cama (zona onde deitar é normal) — falta calibrar com a câmera real
- [ ] Residentes vinculados às câmeras/eventos
- [ ] Implantação na ILPI parceira e calibração com a equipe

---

## Abordagem anterior (YOLOv8) — README original

<details>
<summary>Clique para ver a documentação da primeira versão (YOLOv8 + OpenAI + CustomTkinter)</summary>

### Objetivo do Projeto

Desenvolver um sistema automático de **detecção de quedas em tempo real** que:

✅ Detecta pessoas caídas ou deitadas no chão usando segmentação YOLO v8
✅ Valida detecções com análise de IA (OpenAI GPT-4)
✅ Fornece interface gráfica interativa para monitoramento
✅ Gera alertas imediatos de emergência via WhatsApp
✅ Funciona com webcam em tempo real (30+ FPS)

**Aplicações práticas:**
- Monitoramento de idosos em residências
- Segurança em ambientes hospitalares
- Detecção de acidentes em espaços públicos
- Assistência a pessoas com mobilidade reduzida

---

### Dataset

O dataset foi anotado usando **CVAT (Computer Vision Annotation Tool)** com:

- **926 imagens** coletadas e anotadas manualmente
- **1 classe de segmentação:**
  - `pessoa`: localiza qualquer pessoa no quadro
- **Formato:** Polígonos de segmentação (máscaras) exportadas em formato YOLO
- **Divisão:** ~80% treino, ~20% validação

Estrutura dos dados:
```
dataset2/
├── data.yaml              # Configuração do dataset
├── images/
│   └── train/            # 926 imagens de treino
└── labels/
    └── train/            # 741 máscaras de segmentação (.txt)
```

---

### Como Funciona o Sistema

#### 1. **Captura e Processamento de Frames**
```python
# Thread dedicada para captura otimizada
- Captura frames da webcam em tempo real (640x360)
- Evita buffering para baixa latência
- Sincroniza com thread de inferência
```

#### 2. **Detecção com YOLO v8 Segmentation**
```python
model = YOLO("runs/segment/train3/weights/best.pt")
resultado = model.predict(
    source=frame,
    imgsz=320,           # Tamanho otimizado para velocidade
    conf=0.15,           # Sensibilidade alta para não perder detecções
    iou=0.45,
    max_det=5,
    device="cpu"         # Ou GPU
)
```

**Processos de classificação:**
- **Posição em Pé:** altura/largura da caixa ≥ 1.40
- **Risco de Queda:** altura/largura da caixa < 1.40
- **Limiar ativação:** 2 frames consecutivos em risco

#### 3. **Validação com OpenAI GPT-4**
Quando uma queda é suspeita:

```python
def confirmar_risco_com_openai(frames_base64):
    # Envia 3 frames codificados em base64 para análise
    prompt = """
    Avalie se a pessoa está CAÍDA ou DEITADA no chão.
    Retorne JSON com: risco (0-100), queda (bool), categoria
    """
    resposta = cliente_openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Você é especialista em segurança..."},
            {"role": "user", "content": [{"type": "text", ...}, imagens...]}
        ]
    )
```

**Resposta esperada:**
```json
{
  "risco": 92,
  "queda": true,
  "motivo": "Pessoa claramente deitada no chão",
  "categoria": "queda"
}
```
#### 4. **Envio de alertas por Whatsapp**
O sistema envia alertas de queda com uma imagem capturada do momento do evento diretamente para um contato configurado no WhatsApp. Isso é feito de forma assíncrona para não impactar o desempenho do monitoramento em tempo real e respeita um período de cooldown para evitar spam.

```python
def enviar_alerta_whatsapp_safe():
    # ... (lógica de cooldown e captura de frame)
    threading.Thread(
        target=executar_requisicao_whatsapp, 
        args=(foto_b64,), 
        daemon=True
    ).start()

def executar_requisicao_whatsapp(foto_b64):
    url = "http://localhost:3000/client/sendMessage/ABCD" # Endpoint da API do WhatsApp
    # ... (construção do payload com ou sem imagem em base64 )
    response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=10)
```

Detalhes da Integração:
- **Endpoint da API:** http://localhost:3000/client/sendMessage/ABCD (onde ABCD é o ID da instância ou token da API do WhatsApp ).
- **Chat ID:** O alerta é enviado para o chatId configurado no payload (ex: 556593323330@c.us).
- **Conteúdo:** Inclui uma mensagem de texto e, se disponível, uma imagem do momento da queda codificada em Base64.
- **Cooldown:** Um WHATSAPP_COOLDOWN de 10 segundos é aplicado para evitar múltiplos alertas em um curto período.


#### 5. **Interface Gráfica em Tempo Real**
Interface moderna com **CustomTkinter** mostrando:

-  Vídeo ao vivo com anotações
-  Número de pessoas detectadas
-  FPS e hardware utilizado
-  Status da análise de IA
-  Alerta visual em caso de emergência

---

###  Processo de Treinamento do YOLO

#### Configuração

O arquivo [train.py](train.py) realiza o treinamento supervisionado:

```python
from ultralytics import YOLO

model = YOLO("yolov8n-seg.pt")  # Nano - rápido e leve

model.train(
    data="dataset2/data.yaml",   # Arquivo YAML com paths
    epochs=100,                   # 100 ciclos completos
    imgsz=640,                    # Tamanho padrão de treino
    batch=16,                     # 16 imagens por lote
    workers=4,                    # 4 threads de processamento
    device='cpu',                 # Ou GPU (ex: device=0)
)
```

#### Arquivo de Configuração (data.yaml)

```yaml
path: /path/to/dataset2
train: images/train
val: images/val

nc: 2  # 2 classes
names: ['pessoa_caida', 'pessoa_em_pe']
```

#### Métricas de Treinamento

Após treinamento com 926 imagens, esperamos:

| Métrica | Valor Esperado |
|---------|----------------|
| **mAP50** | ~0.88-0.92 |
| **mAP50-95** | ~0.78-0.85 |
| **Precisão** | ~0.89 |
| **Recall** | ~0.86 |
| **FPS (CPU)** | ~25-30 |
| **FPS (GPU)** | ~100+ |

#### Exemplo de Curva de Treinamento

```
Epoch 1/100:   Loss: 2.45  | mAP50: 0.12
Epoch 10/100:  Loss: 0.89  | mAP50: 0.45
Epoch 30/100:  Loss: 0.34  | mAP50: 0.71
Epoch 50/100:  Loss: 0.18  | mAP50: 0.82
Epoch 100/100: Loss: 0.08  | mAP50: 0.90 ✓
```

Os pesos treinados são salvos em:
```
runs/segment/train3/weights/
├── best.pt    # Melhor modelo (validação)
└── last.pt    # Último checkpoint
```

---

###  Estrutura do Projeto

```
DetectHumans/
├── servidor.py                  #  Servidor atual: visão por pose + API + PWA
├── sentinela_api/  sentinela_pose/  web/   #  API, detector de queda e interface
├── docker-compose.yml           #  PostgreSQL local para desenvolvimento
├── train.py                     #  Script de treinamento YOLO
├── listar_cameras.py            #  Utilitário para listar câmeras da maquina
├── teste_webcam.py              #  Teste de webcam
├── requirements.txt             #  Dependências Python
├── yolov8n.pt                   #  Modelo pré-treinado
├── dataset/                     #  Dataset antigo usando somente 1 pessoas nas fotos de treino
│   ├── data.yaml
│   ├── images/
│   │   ├── train/              # ~741 imagens
│   │   └── val/                # ~185 imagens
│   └── labels/                 # Anotações YOLO
├── dataset2/                    # Dataset atual usando fotos mais variadas e com mais de 1 pessoa
│   ├── data.yaml
│   ├── train.py
│   ├── images/train/
│   └── labels/train/
├── runs/
│   ├── detect/                 # Resultados de detecção
│   └── segment/
│       └── train3/
│           └── weights/
│               ├── best.pt     # Modelo final usado
│               └── last.pt
└── alertas_queda/              #  Alertas salvos automaticamente
```

---

###  Como Executar

#### 1. Instalação de Dependências

```bash
# Criar ambiente virtual (recomendado)
python -m venv .venv

# Ativar (Windows)
.venv\Scripts\activate

# Ou (Linux/Mac)
source .venv/bin/activate

# Instalar dependências
pip install -r requirements.txt
```

#### 2. Treinar o Modelo (Caso for fazer do zero)

```bash
python train.py
```

O treinamento levará entre 1 a 2 dias para treinar e salvará os pesos em `runs/segment/train3/weights/best.pt`.

#### 3. Executar o Sistema de Detecção

```bash
python servidor.py   # fluxo atual (pose + API + PWA); veja a seção do Sentinela acima
```

**Ao iniciar:**
1. Selecione a câmera desejada (0 = integrada, 1 = externa)
2. Aguarde a conexão com a webcam
3. Sistema começa a monitorar automaticamente

**Indicadores Visuais:**
- 🟢 **Verde:** Pessoa em pé, sem risco
- 🔴 **Vermelho:** Queda detectada, alerta ativado
- 🟡 **Amarelo:** Análise com IA em andamento

---

### 🔧 Configurações Importantes

Fluxo antigo (YOLO), histórico: constantes que existiam no `alerta_zap.py` (removido). A configuração atual está no `.env.exemplo_pose`:

```python
# Qualidade da câmera
CAPTURE_WIDTH = 640             # Largura dos frames
CAPTURE_HEIGHT = 360            # Altura dos frames

# Detecção YOLO
INFERENCE_IMGSZ = 320           # Tamanho otimizado para velocidade
INFERENCE_CONF = 0.15           # Confiança mínima
INFERENCE_IOU = 0.45            # Supressão de não-máximo

# Limiares de queda
SUSPEITA_FRAMES_MIN = 2         # Frames para ativar alerta
LIMIAR_EM_PE = 1.40             # Proporção altura/largura

# OpenAI
OPENAI_API_KEY = "sua_chave_aqui"      # .env file
OPENAI_MODEL = "gpt-4o-mini"
TEMPO_COOLDOWN_AI = 4.0         # Segundos entre requisições
```

#### Variáveis de Ambiente (.env)

```
DEVICE=0                        # 0=GPU, cpu=CPU
USE_HALF=0                      # Half precision (0=não, 1=sim)
OPENAI_API_KEY=sk-...          # Sua chave OpenAI
OPENAI_CONFIRMAR_QUEDA=1       # Usar IA para validar (1=sim)
OPENAI_MODEL=gpt-4o-mini       # Modelo a usar
```

---

###  Exemplos de Funcionamento

#### Exemplo 1: Detecção em Tempo Real

```
Frame 1: Pessoa em pé → Postura: "em_pe" → Status: ✅ Normal
Frame 2: Pessoa em pé → Postura: "em_pe" → Status: ✅ Normal
Frame 3: Pessoa caída → Postura: "risco_chao" → Contador: 1
Frame 4: Pessoa caída → Postura: "risco_chao" → Contador: 2 ⚠️ ALERTA!

Enviando para IA...
Resposta: {"risco": 95, "queda": true, "categoria": "queda"}

🚨 EMERGÊNCIA DETECTADA - ALERTA ENVIADO
```

#### Exemplo 2: Métrica de Treinamento (CSV dos Resultados)

```
epoch  box_loss  cls_loss  seg_loss  mAP50  mAP50-95  FPS
0      2.456    0.789    1.234    0.145  0.089    22
10     0.876    0.234    0.567    0.456  0.312    24
50     0.234    0.087    0.156    0.821  0.734    25
100    0.087    0.034    0.067    0.901  0.824    25
```

#### Exemplo 3: Saída do Modelo na GUI

```
┌─────────────────────────────┐
│   GUARDIÃO IA MONITOR       │
├─────────────────────────────┤
│ Status: EMERGÊNCIA / QUEDA  │  🔴 (Vermelho)
│ Pessoas: 1                  │
│ FPS: 28                     │
│ Hardware: CPU               │
│ IA: PERIGO: CHÃO (92%)      │
├─────────────────────────────┤
│ ALERTA ENVIADO              │
└─────────────────────────────┘
```

---

### Troubleshooting

| Problema | Solução |
|----------|---------|
| **Câmera não abre** | Verifique o índice (0 ou 1), ou use `listar_cameras.py` |
| **FPS baixo (< 10)** | Reduza `INFERENCE_IMGSZ` para 256, use GPU |
| **Muitos falsos positivos** | Aumente `INFERENCE_CONF` para 0.25-0.30 |
| **OpenAI timeout** | Verifique chave API, aumente `TEMPO_COOLDOWN_AI` |
| **Out of memory (GPU)** | Reduza `batch` size no treino ou use CPU |

---

### Dependências

Veja `requirements.txt`:

```
opencv-python==4.8.0
ultralytics==8.0.0
torch==2.1.0
torchvision==0.16.0
customtkinter==5.2.0
pillow==10.0.0
openai==1.3.0
python-dotenv==1.0.0
numpy==1.24.3
requests==2.31.0
```

---

### Referências

- **YOLO v8 Docs:** https://docs.ultralytics.com/
- **OpenAI API:** https://platform.openai.com/docs/
- **CVAT Annotation:** https://www.cvat.ai/
- **CustomTkinter:** https://github.com/TomSchimansky/CustomTkinter

---

###  Licença

Este projeto é desenvolvido para fins de aprendizado como parte de projeto integrador, caso a ideia seja reultilizda para outros meios o projeto original deve ser refenciada.

### Proximas Etapas

- aumentar e balancear o dataset;
- melhorar robustez em diferentes ambientes (iluminacao, angulos, oclusao);
- criar logica temporal para diferenciar postura normal de queda;
- integrar alertas para cenarios reais de monitoramento de idosos.

### Observacoes
Este repositorio representa uma etapa importante de base tecnica. O foco futuro e transformar a deteccao de pessoas em uma solucao pratica para **prevencao e resposta a acidentes**, especialmente no contexto de cuidado com idosos.

</details>
