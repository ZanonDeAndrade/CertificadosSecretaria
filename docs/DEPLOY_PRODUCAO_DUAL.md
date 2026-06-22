# Produção Docker: Google Cloud + servidor da faculdade

Este guia usa a mesma imagem Docker nos dois hosts e os mesmos serviços
externos: **Neon PostgreSQL** para metadados e **Google Drive OAuth** para PDFs.
O alvo no Google Cloud é uma **VM Compute Engine**; Cloud Run exige outra
topologia e não deve receber este Compose sem adaptação.

## 1. Topologia e regras

- Somente o Caddy publica portas: `80` e `443`.
- `admin`, `consulta`, `web` e Neon nunca são expostos diretamente.
- Caddy obtém/renova TLS automaticamente quando os domínios são públicos.
- Os dois hosts podem compartilhar Neon e Drive, mas devem usar os **mesmos**
  `JWT_SECRET` e `DOCUMENT_HASH_SECRET`.
- Use um domínio público canônico para os QR Codes. Em failover, altere o DNS;
  não altere `PUBLIC_VALIDATION_BASE_URL`, pois certificados antigos apontam para ele.
- Execute migrations em apenas um host por vez.

## 2. DNS e rede

Crie dois nomes:

```text
certificados.exemplo.edu.br        -> site público
admin-certificados.exemplo.edu.br  -> painel administrativo
```

No Google Compute Engine:

1. Crie VM Ubuntu LTS com IP externo estático, 2 vCPU e 4 GB RAM.
2. Libere TCP `80/443`; restrinja SSH ao IP/VPN da equipe.
3. Aponte os dois registros DNS para o IP estático.
4. Restrinja o domínio administrativo por firewall/VPN quando possível.

No servidor da faculdade, faça o mesmo com DNS/NAT institucional. Se ele for
somente LAN, use `deploy/Caddyfile.internal`, configure DNS interno e instale a
CA do Caddy nos computadores clientes. Essa opção não serve alunos externos.

## 3. Preparar cada host

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# saia e entre novamente

sudo install -d -m 700 /opt/certificados/secrets /opt/certificados/backups
git clone <URL_DO_REPOSITORIO> /opt/certificados/app
cd /opt/certificados/app
cp .env.production.example .env.production
chmod 600 .env.production
```

Copie de forma segura para `/opt/certificados/secrets`:

```text
database_url             connection string pooled do Neon, uma única linha
google_oauth_token.json  token criado por authorize_google_drive.py
jwt_secret               mesmo valor nos dois hosts
document_hash_secret     mesmo valor nos dois hosts; nunca trocar sem migração
```

Gere os dois segredos aleatórios uma vez no host primário e copie os mesmos
arquivos para o secundário:

```bash
openssl rand -base64 48 | tr -d '\n' | sudo tee /opt/certificados/secrets/jwt_secret >/dev/null
openssl rand -base64 48 | tr -d '\n' | sudo tee /opt/certificados/secrets/document_hash_secret >/dev/null
sudo chmod 600 /opt/certificados/secrets/*
```

O token OAuth e a URL Neon não devem aparecer no Git, em screenshots, logs ou
histórico de shell. Rotacione qualquer credencial exposta.

## 4. Configurar `.env.production`

Preencha os domínios, e-mail TLS, ID da pasta Drive e caminhos dos secrets.
Mantenha:

```env
APP_ENV=production
AUTH_COOKIE_SECURE=true
STORAGE_PROVIDER=google_drive
GOOGLE_DRIVE_AUTH_MODE=oauth_user
DATABASE_URL_SECRET_FILE=/opt/certificados/secrets/database_url
GOOGLE_OAUTH_TOKEN_SECRET_FILE=/opt/certificados/secrets/google_oauth_token.json
JWT_SECRET_FILE_HOST=/opt/certificados/secrets/jwt_secret
DOCUMENT_HASH_SECRET_FILE_HOST=/opt/certificados/secrets/document_hash_secret
```

Para o host LAN com CA interna:

```env
CADDY_CONFIG_FILE=./deploy/Caddyfile.internal
```

## 5. Subir ou atualizar

No primeiro host:

```bash
chmod +x deploy/production-up.sh
./deploy/production-up.sh
```

O script valida o Compose, constrói as imagens, aplica Alembic, garante o
template e sobe a stack. No segundo host, aguarde o primeiro terminar e rode o
mesmo comando; a migration será idempotente.

Verificação:

```bash
docker compose --env-file .env.production -f compose.production.yaml ps
docker compose --env-file .env.production -f compose.production.yaml logs --tail=100 admin consulta gateway
curl -fsS "https://$PUBLIC_DOMAIN/health/ready"
curl -fsS "https://$ADMIN_DOMAIN/api/health/ready"
```

Nunca publique `8000`, `8001` ou `8080` no firewall.

## 6. Backup e manutenção

Backup lógico manual do Neon:

```bash
docker compose --env-file .env.production -f compose.production.yaml \
  --profile tools run --rm backup
```

Agende no host primário:

```cron
0 2 * * * cd /opt/certificados/app && docker compose --env-file .env.production -f compose.production.yaml --profile tools run --rm backup
0 3 * * * cd /opt/certificados/app && docker compose --env-file .env.production -f compose.production.yaml exec -T admin python certificados-admin/backEnd/verify_integrity.py
0 * * * * cd /opt/certificados/app && docker compose --env-file .env.production -f compose.production.yaml exec -T admin python certificados-admin/backEnd/reconcile.py
0 4 * * * cd /opt/certificados/app && docker compose --env-file .env.production -f compose.production.yaml exec -T admin python certificados-admin/backEnd/reconcile_drive.py
```

Copie backups para outro local e teste restauração. Backups do Neon não
substituem a exportação independente.

## 7. Failover

1. Confirme que o secundário está saudável e atualizado.
2. Aponte os registros DNS canônicos para o IP secundário.
3. Não execute emissões simultâneas durante a troca de DNS.
4. Após estabilizar, mantenha apenas um host como primário para tarefas cron.

O banco possui constraints/idempotência e suporta múltiplos workers, mas o
procedimento operacional evita migrations concorrentes e manutenção duplicada.

## 8. Checklist obrigatório

- [ ] OAuth do Google em produção e token renovado.
- [ ] URL Neon pooled com `sslmode=require` e senha não exposta.
- [ ] DNS público e admin resolvendo para o host.
- [ ] Portas públicas somente `80/443`.
- [ ] Secrets com modo `600`, iguais nos dois hosts quando indicado.
- [ ] `APP_ENV=production`; URLs e CORS exclusivamente HTTPS.
- [ ] `migrate` concluiu com código zero.
- [ ] `/health/ready` público e admin retornam `200`.
- [ ] Login, emissão sintética, consulta e download testados.
- [ ] Backup, restore e failover testados.
