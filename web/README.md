# Sentinela — PWA do cuidador

Interface baseada no protótipo da documentação (Figuras 10 a 13):

| Tela | Arquivo | Requisitos |
|---|---|---|
| Painel de monitoramento (vídeo ao vivo, indicadores, alertas recentes) | `src/pages/Painel.jsx` | RF08 |
| Histórico de alertas (filtros, foto, Resolver/Falso alarme) | `src/pages/Historico.jsx` | RF09, RF13 |
| Configurações (sensibilidade, câmeras, contatos, nome do cuidador) | `src/pages/Configuracoes.jsx` | RF11, UC09 |
| Alerta em tela cheia (ligar, ver câmera, tratar) | `src/components/AlertaTelaCheia.jsx` | RF05, RF07, UC03, UC04 |
| Layout desktop (barra lateral) / celular (navegação inferior) | `src/components/Layout.jsx` | RNF07 |

## Rodar

```bash
# 1. Backend (na raiz do projeto)
pip install -r requirements_pose.txt
python servidor.py              # http://localhost:8000

# 2. Interface — compilar uma vez (o servidor passa a entregá-la)
cd web
npm install
npm run build

# Desenvolvimento com recarga automática (usa o backend da porta 8000)
npm run dev                     # http://localhost:5173
```

Para abrir no celular na mesma rede: `python servidor.py --host 0.0.0.0` e acesse
`http://IP-DO-COMPUTADOR:8000`. **Ainda não há login** (JWT está previsto na API Node.js),
então use só em rede interna confiável.

## Fluxo em tempo real
- `useTempoReal` abre o WebSocket `/api/ws`: status a cada 1 s e alertas no instante em que surgem.
  Alerta novo → tela cheia vermelha + sirene + vibração + notificação do sistema.
- `VideoAoVivo` busca `/api/quadro` quadro a quadro (pede o próximo só quando o anterior chega e
  pausa com a aba em segundo plano). Não usamos `<img src="/api/video">` (MJPEG) porque o stream
  prende uma conexão e o navegador limita ~6 por servidor: a interface congelava ao trocar de tela.
- `services/api.js` é o único arquivo que conhece as URLs; os dados vêm do banco configurado no
  servidor (PostgreSQL ou SQLite — ver README da raiz).

## Pendências para a próxima etapa (documentação)
- Login JWT e perfis Cuidador/Gestor (RF12).
- Web Push com o app fechado (VAPID, `/push/assinaturas`).
- Cache offline em IndexedDB (hoje: localStorage com os últimos 30 alertas).
