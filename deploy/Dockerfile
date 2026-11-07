# Imagem do Sentinela em MODO PAINEL (API + interface + login + push, sem câmera nem MediaPipe).
# Construir a partir da raiz do projeto:   docker build -f deploy/Dockerfile -t sentinela-painel .

# --- 1) compila a interface (React/Vite) -------------------------------------------------------
FROM node:20-slim AS interface
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- 2) servidor Python ----------------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY deploy/requirements-painel.txt ./
RUN pip install --no-cache-dir -r requirements-painel.txt
COPY sentinela_api ./sentinela_api
COPY sentinela_pose ./sentinela_pose
COPY servidor.py main_pose.py ./
COPY --from=interface /web/dist ./web/dist

# Usuário sem privilégios: se alguém invadir o app, não é root no container.
# UID fixo (10001): é o dono da pasta de fotos montada da VPS (chown 10001:10001 no guia).
RUN useradd --system --uid 10001 --no-create-home sentinela && mkdir -p /app/alertas_queda && chown sentinela /app/alertas_queda
ENV PASTA_FOTOS=/app/alertas_queda
USER sentinela

# O compose/run usa a rede do host: o app escuta só em 127.0.0.1:8090 e o Apache faz o proxy com HTTPS.
CMD ["python", "servidor.py", "--painel", "--host", "127.0.0.1", "--porta", "8090"]
