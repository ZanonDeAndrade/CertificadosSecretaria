# Implantação em servidor Linux local

Este procedimento usa Docker Compose e foi dimensionado para 2 CPUs e 2–4 GB
de RAM. O acesso normal é `http://192.168.2.192`; não há dependência de domínio
público, HTTPS público, Redis ou banco externo.

## 1. Preparar o Linux

Exemplo para Ubuntu/Debian. Ajuste o comando equivalente para outra distribuição.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl git openssl tar gawk ufw iproute2 iputils-ping
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
docker compose version
```

Instale o projeto em um disco com espaço livre suficiente para banco, PDFs e
backups. Reserve pelo menos 5 GB além dos dados esperados.

```bash
sudo mkdir -p /opt/certificados
sudo chown "$USER":"$USER" /opt/certificados
git clone <URL_DO_REPOSITORIO> /opt/certificados
cd /opt/certificados
```

## 2. Configurar ambiente e segredos

```bash
cp .env.local-server.example .env.local-server
nano .env.local-server
./scripts/bootstrap_local_server_secrets.sh secrets/local-server
chmod 700 deploy.sh backup.sh scripts/bootstrap_local_server_secrets.sh
```

Antes do primeiro deploy, preencha `LOCAL_SERVER_URL` com a URL realmente
usada na LAN, por exemplo `http://192.168.2.192`. As variáveis derivadas
`ADMIN_FRONTEND_URL`, `PUBLIC_VALIDATION_BASE_URL` e `CORS_ALLOWED_ORIGINS`
podem permanecer como `${LOCAL_SERVER_URL}`. Não use `localhost` nessas três
variáveis: no navegador de outro computador ele apontaria para o cliente.

O bootstrap gera os arquivos abaixo dentro de `secrets/local-server` com
diretório `0700`. Os arquivos ficam em `0644` por uma limitação do Docker
Compose com secrets baseados em arquivos: os processos não-root dos containers
precisam lê-los após o bind mount. O diretório não pode ser acessado por outros
usuários do host. O bootstrap pede a senha inicial do administrador e nunca a
grava em `.env.local-server`.

| Arquivo | Uso |
| --- | --- |
| `postgres_password` | senha interna do PostgreSQL |
| `database_url` | conexão interna `db:5432` |
| `jwt_secret` | assinatura das sessões HTTP-only |
| `document_hash_keyring` | HMAC de RA/documentos |
| `batch_payload_keys` | criptografia de payload da fila |
| `admin_initial_password` | senha somente para a criação inicial do admin |

Depois que o usuário `admin` existir, remova `ADMIN_INITIAL_USERNAME`,
`ADMIN_INITIAL_NAME`, `ADMIN_INITIAL_ROLE` e `ADMIN_INITIAL_PASSWORD_FILE` de
`.env.local-server`, execute `./deploy.sh` e guarde o arquivo de senha em
cofre externo. Isso impede que uma restauração vazia recrie automaticamente a
conta.

### Variáveis obrigatórias

- `LOCAL_SERVER_URL`: origem HTTP da LAN, sem barra final.
- `POSTGRES_USER` e `POSTGRES_DB`: identificadores do banco; o bootstrap lê
  esses valores e gera a URL interna correspondente. Use letras, números e
  underscore; o padrão é `certificados`.
- `LOCAL_SECRETS_DIR`: normalmente `./secrets/local-server`.
- `ADMIN_INITIAL_USERNAME`/`ADMIN_INITIAL_ROLE`: apenas no primeiro deploy.

As demais variáveis do arquivo modelo possuem valores seguros para a capacidade
indicada. `HTTP_PORT` só deve mudar se a porta 80 já estiver ocupada; o
`deploy.sh` detecta a porta configurada para fazer seu health check.

### Inventário completo de variáveis

Não há variável crítica fora de `.env.local-server.example` ou dos seis arquivos
de secret gerados pelo bootstrap. Não inclua os arquivos de secret no `.env`.

| Classe | Variáveis | Preenchimento no perfil LAN |
| --- | --- | --- |
| **Obrigatória** | `APP_ENV`, `HTTP_PORT`, `LOCAL_SERVER_URL`, `POSTGRES_USER`, `POSTGRES_DB`, `LOCAL_SECRETS_DIR` | Já possuem valores modelo; revise a URL/IP e os identificadores antes do primeiro deploy. |
| **Obrigatória, gerada** | `DATABASE_URL_FILE`, `JWT_SECRET_FILE`, `DOCUMENT_HASH_KEYRING_FILE`, `BATCH_PAYLOAD_KEYS_FILE`, `ADMIN_INITIAL_PASSWORD_FILE`, `POSTGRES_PASSWORD_FILE` | Os caminhos são configurados pelo Compose; o bootstrap cria os respectivos arquivos. Não substitua por valores em texto no `.env`. |
| **Obrigatória para LAN** | `STORAGE_PROVIDER`, `LOCAL_STORAGE_PATH`, `PUBLIC_VALIDATION_BASE_URL`, `PUBLIC_SITE_BASE_PATH`, `CORS_ALLOWED_ORIGINS`, `TRUSTED_PROXY_CIDRS`, `FORWARDED_ALLOW_IPS`, `AUTH_COOKIE_SECURE`, `AUTH_COOKIE_SAMESITE` | Mantenha `local`, `/data/storage`, a origem LAN, `/consulta`, CIDR Docker, `false` e `lax`, respectivamente. |
| **Opcional/tuning** | `TZ`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`, `DB_POOL_PRE_PING`, limites `MAX_*`, `DOWNLOAD_TEMP_DIR`, `JWT_EXPIRES_IN_MINUTES`, `MINIMIZE_DOCUMENT_PLAINTEXT`, `BATCH_*`, `ADMIN_WORKERS`, `CONSULTA_WORKERS` e limites `*_RATE_LIMIT_*` | Os valores modelo foram usados na validação. Ajuste somente após medir carga. |
| **Inicialização única** | `ADMIN_INITIAL_USERNAME`, `ADMIN_INITIAL_NAME`, `ADMIN_INITIAL_ROLE` | Necessárias apenas para criar o primeiro administrador; remova-as junto com `ADMIN_INITIAL_PASSWORD_FILE` após a criação. |
| **Opcional de negócio/operação** | `INSTITUTION_NAME`, `ISSUE_LOCATION`, `SIGNATORY_NAME`, `SIGNATORY_TITLE`, `AUTH_SESSION_RETENTION_DAYS`, `PRIVATE_DATA_RETENTION_DAYS`, `RESTORE_MAX_PDF_MB` | Têm defaults no código; defina-os apenas se a instituição exigir esses valores, retenção ou limite especial no restore administrativo. |
| **Interna do Compose** | `APP_TARGET`, `PORT`, `WEB_CONCURRENCY`, `GOOGLE_DRIVE_ACCESS_MODE` | São definidas por serviço no Compose, não pelo operador no `.env`. |
| **Desenvolvimento/teste, não usar no LAN** | `DATABASE_URL`, `DB_PATH`, `DATABASE_PATH`, `STORAGE_DIR`, `HOST`, `CERTIFICADOS_DISABLE_DOTENV`, `TEST_DATABASE_URL`, `PUBLIC_HTML_DIR`, `PREVIEW_PORT`, `MOCK_API_PORT`, `VITE_API_BASE_URL`, `VITE_PUBLIC_API_BASE_URL` | O perfil Docker já define portas e usa secrets; não configure URLs `localhost` para clientes. |
| **Integração externa, não usar no LAN** | `GOOGLE_*`, `BATCH_WORKER_TRIGGER_URL`, `RESTORE_DATABASE_URL*`, `BACKUP_DESTINATION`, `BACKUP_ENCRYPTION_KEY_FILE` | Google Drive/OAuth e Cloud Run permanecem desativados neste perfil. |

## 3. Subir e validar

```bash
./deploy.sh
curl -i http://127.0.0.1/health
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/health/ready
docker compose --env-file .env.local-server -f compose.local-server.yaml ps
```

`deploy.sh` faz build de produção, inicia PostgreSQL, espera a saúde do banco,
executa `alembic upgrade head`, cria o template padrão, inicia os quatro
serviços e verifica a readiness da API. É idempotente: pode ser executado
novamente após atualização.

Em outro computador da mesma rede, abra:

```text
http://192.168.2.192
```

Teste login, emissão, download, `http://192.168.2.192/consulta/` e um QR Code
em `http://192.168.2.192/validar/CODIGO`.

### Teste obrigatório de outro computador

Este passo **não pode ser substituído** pelo teste local do servidor. No
servidor, confirme o endereço e o serviço publicado:

```bash
ip -4 addr
curl -I http://127.0.0.1
sudo ss -ltnp '( sport = :80 )'
```

O primeiro comando deve mostrar `192.168.2.192` na interface de rede correta.
Em outro computador conectado à mesma LAN, execute:

```bash
ping 192.168.2.192
curl -I http://192.168.2.192
curl -I http://192.168.2.192/consulta/
```

Depois abra no navegador `http://192.168.2.192` e
`http://192.168.2.192/consulta/`; faça login, emita um certificado de teste e
baixe-o. Se falhar, confira máscara/gateway no `ip -4 addr`, porta 80 no
`ss`, regras UFW, isolamento de clientes Wi-Fi/VLAN e se o computador cliente
está na mesma rota LAN. Não use `localhost` no navegador do cliente.

## 4. Firewall e inicialização automática

Exponha somente SSH e HTTP na rede local. PostgreSQL (`5432`), FastAPI (`8000`
e consulta (`8001`) não devem ser abertos: não são publicados pelo Compose.
Se a rede for `192.168.2.0/24`, restrinja explicitamente as regras a ela;
substitua o CIDR se a máscara real mostrada pelo servidor for diferente.

```bash
sudo ufw allow from 192.168.2.0/24 to any port 22 proto tcp
sudo ufw allow from 192.168.2.0/24 to any port 80 proto tcp
sudo ufw enable
sudo ufw status verbose
sudo systemctl enable --now docker
```

As políticas `restart: unless-stopped` fazem os containers iniciarem junto com
o Docker depois de reboot. Verifique com `sudo reboot` e, após reconectar:

```bash
cd /opt/certificados
docker compose --env-file .env.local-server -f compose.local-server.yaml ps
curl --fail http://127.0.0.1/api/health/ready
```

## 5. Logs, espaço e manutenção

```bash
docker compose --env-file .env.local-server -f compose.local-server.yaml logs -f --tail=200 web admin worker
docker stats
df -h
docker system df
docker compose --env-file .env.local-server -f compose.local-server.yaml exec admin du -sh /data/storage
du -sh backups 2>/dev/null
```

Logs seguem para `docker logs`; configure rotação do daemon Docker no host,
por exemplo `/etc/docker/daemon.json`:

```json
{"log-driver":"local","log-opts":{"max-size":"10m","max-file":"3"}}
```

Reinicie Docker após editar esse arquivo: `sudo systemctl restart docker`.
Limites de planilha (10 MB/2000 linhas), PDF (10 MB) e ZIP (100 MB) já evitam
uso acidental excessivo de memória e disco. Revise o crescimento de
`runtime/storage` mensalmente; não há retenção automática de certificados
porque eles são documentos institucionais.

O Docker também acumula cache de build em cada atualização. Depois de confirmar
que o deploy está saudável, remova apenas cache/imagens não usados, nunca
volumes:

```bash
docker builder prune -af --filter until=168h
docker image prune -f
```

Guarde backups fora do disco do servidor e retenha, por exemplo, 30 dias.
Antes de excluir arquivos antigos, liste-os e confirme que existe cópia externa:

```bash
find /mnt/backup/certificados -type f -mtime +30 -print
```

## 6. Atualizar

```bash
cd /opt/certificados
./backup.sh /mnt/backup/certificados
git pull --ff-only
./deploy.sh
curl --fail http://127.0.0.1/api/health/ready
```

Não execute `docker compose down -v`: a opção `-v` apaga o volume persistente
do PostgreSQL. `docker compose down` sem `-v` é seguro e `./deploy.sh` recria
os serviços sem apagar dados.

## 7. Backup e restauração

Faça backup em disco externo ou compartilhamento de rede montado, não apenas
no disco do servidor:

```bash
./backup.sh /mnt/backup/certificados
```

O script cria três arquivos com timestamp: dump PostgreSQL customizado, tar.gz
de `runtime/storage` e tar.gz da configuração/segredos. Ele falha em caso de
colisão; não sobrescreve backups.

Restaure somente com a aplicação parada e após copiar os três artefatos ao
servidor. Substitua os nomes pelos arquivos desejados:

```bash
docker compose --env-file .env.local-server -f compose.local-server.yaml down
docker compose --env-file .env.local-server -f compose.local-server.yaml up -d db
docker compose --env-file .env.local-server -f compose.local-server.yaml exec -T db \
  sh -ec 'dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"'
docker compose --env-file .env.local-server -f compose.local-server.yaml exec -T db \
  sh -ec 'createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
cat /mnt/backup/certificados/postgres-AAAAmmdd-HHMMSS.dump | \
  docker compose --env-file .env.local-server -f compose.local-server.yaml exec -T db \
  sh -ec 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-acl'
rm -rf runtime/storage "$(awk -F= '/^LOCAL_SECRETS_DIR=/{print $2; exit}' .env.local-server)"
tar -xzf /mnt/backup/certificados/storage-AAAAmmdd-HHMMSS.tar.gz -C runtime
tar -xzf /mnt/backup/certificados/config-AAAAmmdd-HHMMSS.tar.gz
./deploy.sh
```

Execute um restore de teste em máquina ou disco separado periodicamente. Um
backup armazenado no mesmo disco não protege contra falha física, ransomware ou
roubo do servidor.

## 8. Integrações externas e limitações

| Integração | Necessária no perfil LAN | Funciona sem domínio/HTTPS | Limitação |
| --- | --- | --- | --- |
| PostgreSQL | Sim | Sim, interno Docker | não publicar a porta |
| PDFs locais | Sim | Sim | requer backup externo e espaço em disco |
| Google Drive/OAuth/Picker | Não | Não configurado | exige credenciais, callback registrado e normalmente HTTPS/domínio para uso seguro |
| SMTP | Não detectado | — | não há envio de e-mail implementado |
| Mercado Pago | Não detectado | — | não há integração no projeto |
| Google Maps | Não detectado | — | não há integração no projeto |
| Webhooks públicos | Não detectado | — | LAN não recebe callbacks da internet |

O frontend pode manter código do Google Drive, mas `STORAGE_PROVIDER=local`
desativa sua exigência para emitir certificados. Para ativar Drive no futuro,
use o perfil de produção existente com credenciais e HTTPS; não basta mudar a
variável local.

## 9. Problemas comuns

- **Porta 80 ocupada:** descubra com `sudo ss -ltnp '( sport = :80 )'` e pare o
  serviço conflitante, ou defina `HTTP_PORT=8080` e acesse com `:8080`.
- **Login não mantém sessão:** confirme que a URL do navegador é exatamente
  `LOCAL_SERVER_URL`, `AUTH_COOKIE_SECURE=false` e não há proxy externo.
- **API retorna 503:** execute `docker compose ... logs --tail=200 admin db` e
  confirme a existência de todos os arquivos em `secrets/local-server`.
- **PDF não baixa:** confirme `runtime/storage/pdfs`, permissões e espaço com
  `df -h`; consulte os logs de `consulta`.
- **Worker parado:** `docker compose ... restart worker`; os lotes ficam no
  PostgreSQL e podem ser retomados sem perder dados.
- **Worker unhealthy:** consulte `docker compose ... logs --tail=200 worker db`.
  O healthcheck faz um `SELECT 1` no PostgreSQL; a fila usa bloqueio/lease no
  banco, portanto dois workers não assumem o mesmo lote simultaneamente.

## 10. Estado da validação

**Validado no ambiente de preparação:** build de produção, `deploy.sh`, banco
PostgreSQL, migrations, health checks, login HTTP com cookie `HttpOnly`/
`SameSite=Lax`, emissão sintética, upload, geração e download de PDF, worker,
persistência após reinício dos containers, Nginx (SPA, `/consulta/`, cache e
compressão) e `backup.sh`. O backup continha dump do banco, storage e
configuração/segredos.

**Ainda obrigatório no servidor real:** confirmar `192.168.2.192` com
`ip -4 addr`, aplicar firewall, executar o teste de outro computador acima,
testar `sudo reboot`, medir espaço/RAM após carga real e realizar um restore em
ambiente separado. Não marque esses itens como concluídos antes desses testes.
