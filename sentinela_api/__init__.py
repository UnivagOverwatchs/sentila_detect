"""
sentinela_api - API leve do Serviço de Visão para a PWA do Sentinela.

ARQUITETURA (etapa atual, conforme combinado)
---------------------------------------------
    Webcam/RTSP -> ServicoVisao (thread: pose + lógica de queda)
                       |  grava eventos/alertas
                       v
                  Banco (SQLite, mesmo modelo lógico da documentação)
                       ^
                       |  REST + WebSocket + vídeo MJPEG
                  FastAPI (app.py)  <---- PWA React (pasta web/)

Na documentação, a API definitiva é Node.js + PostgreSQL. As rotas daqui usam
os mesmos recursos (/alertas, /cameras, /configuracao...) para que a PWA possa
trocar de backend sem mudar as telas.

Módulos:
    banco.py          -> persistência SQLite (camera, evento, alerta, contato, configuracao)
    sensibilidade.py  -> converte o slider 0..100% nos limiares do detector
    servico_visao.py  -> loop de visão em thread + frame atual + status
    app.py            -> rotas HTTP/WebSocket e arquivos da PWA
"""
