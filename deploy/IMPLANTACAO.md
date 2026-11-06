# Implantação do painel na VPS (AlmaLinux + Docker + Apache)

Resultado: `https://painel.sentinelaunivag.com.br` com login, usando o PostgreSQL que já existe na VPS.
O computador com a câmera continua detectando e gravando os alertas no mesmo banco.

> **Segredos:** a senha do banco, a senha do administrador e as chaves VAPID são digitadas direto no
> terminal da VPS. Não as envie por chat, e-mail nem commit.

## Visão geral

```
celular / PC ──HTTPS──> Apache (80/443) ──> container sentinela-painel (127.0.0.1:8090) ──> Postgres (127.0.0.1:5432)
PC com a câmera ───────────────────────────────────────────────────────────────────────────> mesmo Postgres
```

Limitações desta etapa: sem vídeo ao vivo e sem foto dos alertas no painel da VPS (os arquivos ficam no PC
com a câmera); a sensibilidade escolhida no painel vale para o detector depois que ele reiniciar.

## 0. Antes de começar (no Termius, só leitura)

```bash
docker --version
ss -tlnp | grep ':8090 ' ; echo "porta 8090 livre se nada apareceu acima"
httpd -M | grep -E 'headers|proxy_wstunnel|ssl|rewrite'
getenforce
```

Precisa aparecer `headers_module`, `proxy_wstunnel_module`, `ssl_module` e `rewrite_module`.
Se faltar `headers_module`, apague as quatro linhas `Header always set` do arquivo `apache-443.conf`.

## 1. Enviar o pacote

No PC, gere o pacote (já feito: `sentinela-painel.tar.gz` na pasta do projeto). No Termius, aba **SFTP**,
envie o arquivo para a pasta `/opt/` da VPS.

## 2. Descompactar e criar o `.env`

```bash
mkdir -p /opt/sentinela
cd /opt/sentinela
tar xzf /opt/sentinela-painel.tar.gz
cp deploy/env.painel.exemplo .env
chmod 600 .env
nano .env
```

No `nano`, troque os três `COLE_...`: a senha do banco e as duas chaves VAPID (copie as linhas
`VAPID_PUBLIC_KEY` e `VAPID_PRIVATE_KEY` do `.env` do computador que detecta as quedas; precisam ser as mesmas).
Salve com `Ctrl+O`, Enter, e saia com `Ctrl+X`.

## 3. Construir a imagem (leva alguns minutos)

```bash
cd /opt/sentinela
docker build -f deploy/Dockerfile -t sentinela-painel .
```

## 4. Criar o administrador (a senha é pedida no terminal)

```bash
docker run --rm -it --network host --env-file .env sentinela-painel \
  python -m sentinela_api.usuarios criar --usuario admin --nome "Administrador" --papel ADMIN
```

## 5. Subir o painel

```bash
docker run -d --name sentinela-painel --restart unless-stopped --network host --env-file .env sentinela-painel
sleep 5
curl -s http://127.0.0.1:8090/api/eu
```

Deve responder `{"login_obrigatorio":true,"usuario":null}`. Se não, veja `docker logs sentinela-painel`.

## 6. Apache: porta 80 e certificado

```bash
setsebool -P httpd_can_network_connect 1
cp deploy/apache-80.conf /etc/httpd/conf.d/sentinela-painel-80.conf
apachectl configtest
systemctl reload httpd
certbot certonly --webroot -w /var/www/html -d painel.sentinelaunivag.com.br \
  --deploy-hook "systemctl reload httpd"
```

O `certbot` pede um e-mail (avisos de renovação) e a aceitação dos termos: responda no terminal.

## 7. Apache: HTTPS

```bash
cp deploy/apache-443.conf /etc/httpd/conf.d/zz-sentinela-painel-443.conf
apachectl configtest
systemctl reload httpd
```

Abra `https://painel.sentinelaunivag.com.br`: deve aparecer a tela de login.

## 8. Renovação automática do certificado

```bash
certbot renew --dry-run
systemctl list-timers | grep -i certbot
```

O `--dry-run` deve terminar com "simulated renewal succeeded". Se não houver um timer do certbot, avise.

## 9. No computador que detecta as quedas

Nada muda no código. Só confira que o `.env` dele continua apontando para o mesmo banco e usa as mesmas
chaves VAPID. Os celulares se cadastram **no endereço novo** (Configurações → Ativar notificações).

## 10. Avisos por WhatsApp (opcional, repositório `sentinela_whatsapp`)

O notificador (`UnivagOverwatchs/sentinela_whatsapp`) roda em containers próprios (`whatsapp-api` + `notificador`),
lê o **mesmo PostgreSQL** e envia a mensagem aos contatos de emergência. Quem detecta (o computador com a câmera)
apenas o acorda por `POST /notificar`; o painel da VPS **não** detecta nem avisa, só mostra os alertas.

1. Suba o notificador seguindo o README daquele repositório (`compose.servidor.yaml`, `.env` com `PG*`,
   `NOTIF_TOKEN` e `--parear` para o QR Code na primeira vez).
2. No `.env` do **computador que detecta**, defina `NOTIFICADOR_URL=http://<servidor-do-notificador>:8100` e
   `NOTIFICADOR_TOKEN=<o mesmo NOTIF_TOKEN>`. Deixe `WHATSAPP_URL` vazio, senão a mensagem sai em dobro.
3. Libere a porta 8100 no firewall só para o IP do computador que detecta.
4. Teste: `curl http://<servidor>:8100/saude` deve mostrar `"whatsapp_conectado": true`.

Se o aviso imediato falhar, o notificador encontra o alerta sozinho no banco em poucos segundos.
Limitação atual: a foto do alerta só entra na mensagem se o notificador alcançar `SENTINELA_API_URL`
(a API do computador que detecta), pois o painel da VPS não tem as fotos.

## Atualizar depois

Envie um pacote novo, descompacte por cima (o `.env` não está no pacote) e rode:

```bash
cd /opt/sentinela
docker build -f deploy/Dockerfile -t sentinela-painel .
docker rm -f sentinela-painel
docker run -d --name sentinela-painel --restart unless-stopped --network host --env-file .env sentinela-painel
```

## Desfazer

```bash
docker rm -f sentinela-painel
rm /etc/httpd/conf.d/sentinela-painel-80.conf /etc/httpd/conf.d/zz-sentinela-painel-443.conf
systemctl reload httpd
```

Os outros containers (`sentinela`, `sentinela-dashboard` etc.) não são tocados em nenhum passo.

## Depois do painel no ar (próxima etapa de segurança)

- Trocar a senha do root e a do Postgres.
- Prender o Postgres a `127.0.0.1` (hoje `0.0.0.0:5432` está aberto à internet): exige recriar o container
  `sentinela` com `-p 127.0.0.1:5432:5432`, reaproveitando o mesmo volume, **depois de um `pg_dump`**.
  Atenção: o computador com a câmera deixa de alcançar o banco direto; ele precisará de um túnel SSH ou do
  endpoint de envio (próximo PR).
- Revisar o firewall (FTP, e-mail, DNS, cockpit e portas altas abertas).
