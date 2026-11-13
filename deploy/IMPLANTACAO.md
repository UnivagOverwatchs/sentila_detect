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

As fotos dos alertas que os agentes enviam ficam numa pasta da VPS, fora do container (sobrevivem a atualizações):

```bash
mkdir -p /opt/sentinela/dados/alertas
chown 10001:10001 /opt/sentinela/dados/alertas
```

```bash
docker run -d --name sentinela-painel --restart unless-stopped --network host --env-file .env \
  -v /opt/sentinela/dados/alertas:/app/alertas_queda sentinela-painel
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

## 9. Agente de visão (recomendado): câmera em qualquer lugar, alertas e fotos no painel

O **agente** (`agente.py`) roda onde a câmera é alcançável (um computador pequeno no local da câmera) e envia ao
painel, por HTTPS, o alerta, uma foto do momento e um quadro por segundo para a tela "ao vivo". O vídeo **não sai**
do local, e o computador do agente **não precisa** alcançar o banco: com isso dá para fechar a porta 5432.

0. **Pelo painel (mais fácil):** entre como administrador em *Configurações → Agentes de câmera → Adicionar câmera*,
   dê um nome ao computador e copie as linhas do `.env` que a tela mostra (a chave aparece uma vez). Dá para trocar a
   chave ou revogar o acesso ali mesmo. Se preferir a linha de comando, siga o passo 1.

1. **Na VPS**, crie a chave do agente (aparece UMA vez; guarde num gerenciador de senhas):

```bash
docker exec -it sentinela-painel python -m sentinela_api.agentes criar --nome "Quarto 1"
```

   Outros comandos: `listar`, `nova-chave --nome ...` (a chave antiga deixa de valer) e `revogar --nome ...`.

2. **No computador da câmera**, no `.env` (a chave NUNCA vai na linha de comando):

```
SENTINELA_URL=https://painel.sentinelaunivag.com.br
SENTINELA_TOKEN=<a chave do passo 1>
CAMERA_FONTE=0          # 0 = webcam; ou rtsp://usuario:senha@IP-DA-CAMERA:554/caminho
CAMERA_NOME=Quarto 1
CAMERA_LOCAL=Térreo
```

3. Instale as dependências (`pip install -r requirements_pose.txt`) e rode `python agente.py`. A câmera aparece no
   painel, e a sensibilidade, a câmera ligada/desligada e a **área da cama** marcadas no painel chegam ao agente em
   até 10 s, sem reiniciar.
4. Se a internet cair, os alertas ficam na pasta `fila_agente/` e seguem quando ela voltar (até depois de reiniciar).
   A foto local é apagada depois do envio (`AGENTE_GUARDAR_FOTOS=1` mantém).
5. Em redes onde o IPv6 trava, ponha `AGENTE_FORCAR_IPV4=1` no `.env` do agente.

O push e o WhatsApp saem **do painel**, no instante em que o alerta chega; o computador do agente não precisa de
chaves VAPID nem do token do notificador.

> O fluxo antigo (computador com câmera gravando direto no PostgreSQL com `servidor.py`) continua funcionando, mas
> exige expor o banco e não mostra vídeo nem fotos no painel da VPS.

## 9b. Computador que grava direto no banco (fluxo antigo)

Nada muda no código. Só confira que o `.env` dele continua apontando para o mesmo banco e usa as mesmas
chaves VAPID. Os celulares se cadastram **no endereço novo** (Configurações → Ativar notificações).

## 10. Avisos por WhatsApp (opcional, repositório `sentinela_whatsapp`)

O notificador (`UnivagOverwatchs/sentinela_whatsapp`) roda em containers próprios (`whatsapp-api` + `notificador`)
**na mesma VPS**, lê o **mesmo PostgreSQL** e envia a mensagem aos contatos de emergência. Quando um agente envia um
alerta, o **painel** acorda o notificador por `POST /notificar` (e avisa "câmera sem sinal" por `POST /aviso`).

1. Suba o notificador seguindo o README daquele repositório (`compose.servidor.yaml`, `.env` com `PG*`,
   `NOTIF_TOKEN` e `--parear` para o QR Code na primeira vez). O compose já publica a porta só em
   `127.0.0.1:8100` (fechada para a internet: o token não trafega aberto) e monta a pasta de fotos do painel
   **só para leitura**, para a mensagem sair com a foto mesmo com o login ligado.
2. No `.env` do **painel** (`/opt/sentinela/.env`), defina `NOTIFICADOR_URL=http://127.0.0.1:8100` e
   `NOTIFICADOR_TOKEN=<o mesmo NOTIF_TOKEN>`; recrie o container do painel.
3. Teste: `curl http://127.0.0.1:8100/saude` (na VPS) deve mostrar `"whatsapp_conectado": true`.

Se o aviso imediato falhar, o notificador encontra o alerta sozinho no banco em poucos segundos.
No fluxo antigo (computador gravando direto no banco), defina `NOTIFICADOR_URL` nele também; nesse caso a porta
8100 precisa ficar acessível para ele (publique `8100:8100` e libere no firewall **só para o IP dele**).

## Atualizar depois

Envie um pacote novo, descompacte por cima (o `.env` não está no pacote) e rode:

```bash
cd /opt/sentinela
docker build -f deploy/Dockerfile -t sentinela-painel .
docker rm -f sentinela-painel
docker run -d --name sentinela-painel --restart unless-stopped --network host --env-file .env \
  -v /opt/sentinela/dados/alertas:/app/alertas_queda sentinela-painel
```

## Desfazer

```bash
docker rm -f sentinela-painel
rm /etc/httpd/conf.d/sentinela-painel-80.conf /etc/httpd/conf.d/zz-sentinela-painel-443.conf
systemctl reload httpd
```

Os outros containers (`sentinela`, `sentinela-dashboard` etc.) não são tocados em nenhum passo.

## Depois do painel no ar (segurança da VPS)

Faça nesta ordem, **com um backup feito antes** (seção "Backup"):

1. **Trocar as senhas** do root e do Postgres (`ALTER USER sentinelas PASSWORD '...';` e atualizar os `.env`).
2. **Fechar o Postgres para a internet** (hoje `0.0.0.0:5432` está aberto): recrie o container `sentinela`
   publicando só no próprio servidor, reaproveitando o mesmo volume de dados:
   ```bash
   docker inspect sentinela --format '{{json .Mounts}}'      # anote o volume/pasta dos dados
   docker stop sentinela && docker rename sentinela sentinela-antigo
   docker run -d --name sentinela --restart unless-stopped -p 127.0.0.1:5432:5432 \
     -v <MESMO_VOLUME>:/var/lib/postgresql/data <MESMA_IMAGEM_E_VARIAVEIS_DO_ANTIGO>
   # conferiu que o painel funciona? então:  docker rm sentinela-antigo
   ```
   Com o **agente de visão**, nenhum computador externo precisa do banco. Computadores do fluxo antigo passam a usar
   um túnel SSH (`ssh -N -L 5432:127.0.0.1:5432 usuario@VPS`) ou migram para o agente.
3. **Firewall: só o necessário aberto** (AlmaLinux usa firewalld):
   ```bash
   firewall-cmd --list-all                                   # veja o que está aberto hoje
   for s in ftp smtp pop3 imap dns cockpit; do firewall-cmd --permanent --remove-service=$s; done
   firewall-cmd --permanent --add-service=ssh --add-service=http --add-service=https
   firewall-cmd --permanent --remove-port=5432/tcp           # e as "portas altas" que aparecerem na lista
   firewall-cmd --reload && firewall-cmd --list-all
   ```
   Atenção: o Docker publica portas por fora do firewalld; por isso o item 2 (publicar só em 127.0.0.1) é essencial.
4. **SSH contra força bruta**: `dnf install -y epel-release fail2ban && systemctl enable --now fail2ban`
   (a configuração padrão já protege o `sshd`). Se possível, entre só com chave (`PasswordAuthentication no`).
5. **CSP**: depois de usar o painel e a câmera do navegador por alguns dias sem avisos de CSP no console,
   troque `Content-Security-Policy-Report-Only` por `Content-Security-Policy` no `zz-sentinela-painel-443.conf`.
