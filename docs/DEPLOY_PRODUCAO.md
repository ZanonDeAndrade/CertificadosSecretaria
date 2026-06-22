# Deploy em produção — Google Cloud Run + servidor local

Guia único para subir o sistema em **três ambientes que formam UM sistema só**:
todos compartilham o **mesmo Neon (Postgres)** e o **mesmo Google Drive**, e os
QR Codes dos certificados apontam para **uma única URL pública canônica**.

```
            UM sistema · mesmo Neon · mesmo Drive · uma URL pública canônica (QR)

  Secretaria ─▶ Cloud Run: painel React/nginx ─▶ Cloud Run: admin ─┐
                                                                  ├─▶ Neon (Postgres)
  Alunos ─────▶ Cloud Run: consulta (site público) ────────────────┘   + Google Drive (PDFs)
                   ▲ URL canônica do QR

  Faculdade (LAN) ─▶ Servidor local: Docker Compose (Caddy+nginx+admin+consulta) → mesmo Neon+Drive
```

O backend gera PDF e fala com o Drive, portanto usa container. O painel também é
servido no Cloud Run por nginx e chama `/api` na própria origem; o nginx encaminha
para o serviço admin. Assim o cookie de login permanece first-party. O mesmo build
do painel também serve no nginx do servidor local.

---

## 0. Recursos compartilhados (faça uma vez)

### Neon (Postgres)
1. Crie um projeto no [Neon](https://neon.tech) e copie a **connection string**
   *pooled* (`...-pooler...`, com `?sslmode=require`).
2. Inicialize o schema + template padrão (de qualquer máquina com a string):
   ```bash
   export DATABASE_URL='postgresql://USER:PASS@HOST-pooler/db?sslmode=require'
   export APP_ENV=production
   alembic upgrade head
   python certificados-admin/backEnd/seed_template.py
   python certificados-admin/backEnd/create_admin.py <usuario> <senha> --role admin
   ```
   (No Cloud Run isso também pode rodar como Job — `deploy/cloudrun/deploy.sh migrate`.)

### Google Drive
- Pasta (ou Shared Drive) dedicada para os PDFs. Use o **mesmo** `FOLDER_ID` em
  todos os ambientes. Autorize o acesso (OAuth do usuário ou service account) e
  guarde o token/JSON como **segredo** (nunca no git). Detalhes em
  [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md) e [DEPLOY_E_RECUPERACAO.md](DEPLOY_E_RECUPERACAO.md).

### Segredos (mesmos valores em todos os ambientes)
`DATABASE_URL` (Neon), `JWT_SECRET`, `DOCUMENT_HASH_SECRET` (`openssl rand -base64 48`),
e o token/JSON do Drive. **`DOCUMENT_HASH_SECRET` precisa ser idêntico em todo lugar**
(senão o hash de documento e os links de download por nome divergem).

> ⚠️ **A URL do QR é gravada dentro de cada PDF, para sempre.** Defina a URL pública
> canônica **antes de emitir certificados reais**. A URL do Cloud Run (`*.run.app`)
> é estável e serve para começar; se for ter domínio próprio, configure-o **antes**
> de emitir em produção (senão os QRs antigos continuarão apontando para `run.app`).

---

## 1. Google Cloud Run — painel + admin + consulta

Duas imagens e três serviços: uma imagem Python atende `admin` e `consulta`, e
uma imagem nginx atende o painel React.
Script pronto em [`deploy/cloudrun/deploy.sh`](../deploy/cloudrun/deploy.sh).

```bash
gcloud auth login
./deploy/cloudrun/deploy.sh status          # confere o ambiente atual
./deploy/cloudrun/deploy.sh release         # build + migrations + deploy dos três serviços
```

Ordem por causa das URLs (interdependência normal):
1. **Deploy do `consulta`** → copie a URL `https://consulta-XXXX.run.app`.
2. Cole essa URL em `PUBLIC_VALIDATION_BASE_URL` (no script) e **rode `consulta` e
   `admin` de novo** para gravar a URL canônica nos dois.
3. **Deploy do `admin`** → copie o hostname para `ADMIN_API_HOST` do painel.
4. **Deploy do `painel`** → coloque sua URL em `ADMIN_FRONTEND_URL` e
   `CORS_ALLOWED_ORIGINS` do admin.

Notas: `--timeout 900` no admin cobre lotes grandes; `min-instances 0` economiza
(aceita cold start de alguns segundos); o `--forwarded-allow-ips="*"` do uvicorn já
resolve o IP real do cliente para os rate limits (deixe `TRUSTED_PROXY_CIDRS` vazio).

---

## 2. Painel React no Cloud Run

O [`Dockerfile.cloudrun-web`](../deploy/Dockerfile.cloudrun-web) compila o React
com `VITE_API_BASE_URL=/api`. O nginx usa
[`nginx.cloudrun.conf`](../deploy/nginx.cloudrun.conf) para encaminhar `/api` ao
serviço admin. O comando `deploy/cloudrun/deploy.sh release` constrói e publica
essa imagem junto com os backends. A Vercel continua possível como alternativa,
mas exige adicionar sua URL exata ao CORS do admin.

---

## 3. Servidor local da faculdade — Docker Compose

A stack local já está pronta em [`compose.production.yaml`](../compose.production.yaml)
(Caddy TLS + nginx + admin + consulta), e **não sobe Postgres** — usa o **mesmo Neon**.

```bash
cp .env.production.example .env.production   # ajuste domínios/limites (sem segredos aqui)
# coloque os segredos em arquivos no host (caminhos do .env.production):
#   /opt/certificados/secrets/{database_url,jwt_secret,document_hash_secret,google_oauth_token.json}
docker compose --env-file .env.production -f compose.production.yaml \
  --profile tools run --rm migrate          # (opcional; o Neon já foi migrado no passo 0)
docker compose --env-file .env.production -f compose.production.yaml up -d --build
```

Use **a mesma `PUBLIC_VALIDATION_BASE_URL`** (a URL canônica do `consulta` no Cloud
Run) no `.env.production` local, para os QRs gerados aqui apontarem ao mesmo site.
Sem domínio público, use `deploy/Caddyfile.internal` + DNS interno (LAN). Detalhes
em [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md).

---

## Matriz de variáveis (o essencial)

| Variável | admin | consulta | local | Valor |
|---|:--:|:--:|:--:|---|
| `APP_ENV` | ✅ | ✅ | ✅ | `production` |
| `DATABASE_URL` (segredo) | ✅ | ✅ | ✅ | Neon pooled, `sslmode=require` |
| `STORAGE_PROVIDER` | ✅ | ✅ | ✅ | `google_drive` |
| `GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID` | ✅ | ✅ | ✅ | mesma pasta |
| token/JSON do Drive (segredo) | ✅ | ✅ | ✅ | OAuth ou service account |
| `DOCUMENT_HASH_SECRET` (segredo) | ✅ | ✅ | ✅ | **idêntico em todo lugar** |
| `PUBLIC_VALIDATION_BASE_URL` | ✅ | ✅ | ✅ | URL canônica do `consulta` (QR) |
| `JWT_SECRET` (segredo) | ✅ | — | ✅ | aleatório |
| `ADMIN_FRONTEND_URL` / `CORS_ALLOWED_ORIGINS` | ✅ | — | ✅ | URL do painel (Vercel/local) |
| `AUTH_COOKIE_SECURE` | ✅ | — | ✅ | `true` (HTTPS) |
| `AUTH_COOKIE_SAMESITE` | ✅ | — | ✅ | `lax` (painel e API same-site via rewrite) |
| `VITE_API_BASE_URL` (build do painel) | — | — | — | `/api` (padrão em prod) |

---

## Operação e checklist

- **Backups:** o Neon tem PITR próprio; ative a retenção desejada. O Drive tem sua
  redundância. O backup crítico é o **mapa código↔arquivo** (o Postgres).
- **Tarefas periódicas** (cron, em qualquer ambiente com acesso ao Neon/Drive):
  `verify_integrity.py` (integridade dos PDFs), `reconcile.py` e `reconcile_drive.py`
  (órfãos/pendentes). Veja [DEPLOY_E_RECUPERACAO.md](DEPLOY_E_RECUPERACAO.md).
- **Smoke test:** login no painel (Vercel) → emitir 1 planilha de teste (dados
  sintéticos) → abrir o QR (vai ao `consulta` no Cloud Run) → baixar o PDF.
- **Custom domain (depois):** mapeie um domínio no Cloud Run para o `consulta` e use
  um subdomínio para o `admin` no **mesmo** domínio do painel → aí dá para trocar o
  rewrite por chamada direta com cookie `SameSite=Lax` first-party.

Arquitetura e recuperação detalhadas: [ARQUITETURA.md](ARQUITETURA.md) ·
[DEPLOY_E_RECUPERACAO.md](DEPLOY_E_RECUPERACAO.md).
