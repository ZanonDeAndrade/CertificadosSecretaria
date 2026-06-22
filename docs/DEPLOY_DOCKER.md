# Deploy no servidor da faculdade (Docker) — guia detalhado

Servidor-alvo: **Linux, 2 núcleos, 2–4 GB RAM, 20–25 GB disco**.
Decisões adotadas (suas respostas):

- **Armazenamento dos PDFs:** Google Drive (modo produção do app, PDFs fora do disco).
- **Admin:** aberto na internet, protegido por login (ver “Endurecer depois”).
- **TLS/Domínio:** ainda não há domínio → **fase de teste em HTTP**; quando o
  domínio sair, migra-se para HTTPS (seção final).

Tudo já vem pronto no repositório: `Dockerfile`, `docker-compose.yml`,
`deploy/Dockerfile.web`, `deploy/nginx.conf`, `.env.docker.example`.

---

## 0. Visão geral da stack

```
            porta 80                 porta 8080
  Aluno ───────────────▶ ┌──────────────────────────┐
                         │   web (nginx)            │
  Secretaria ──────────▶ │  / → consulta            │
                         │  :8080 → SPA + /api→admin │
                         └────────┬─────────┬───────┘
                                  │         │
                         ┌────────▼──┐  ┌───▼─────────┐     ┌──────────────┐
                         │ consulta  │  │   admin     │────▶│ Google Drive │ (PDFs)
                         │  :8001    │  │   :8000     │     └──────────────┘
                         └─────┬─────┘  └──────┬──────┘
                               └─────┬─────────┘
                                ┌────▼────┐
                                │   db    │ (PostgreSQL — metadados)
                                │ volume  │
                                └─────────┘
```

Containers: `db` (Postgres), `migrate` (roda 1x), `admin`, `consulta`, `web` (nginx).

---

## 1. Preparar o servidor

```bash
# Docker Engine + Compose plugin (Debian/Ubuntu)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER     # relogar depois
docker --version && docker compose version

# Clonar o projeto
git clone <URL_DO_REPO> certificados && cd certificados
```

Requisitos: **internet de saída** liberada para `*.googleapis.com` (Drive) e para
o registro do Docker. O servidor não precisa de Python/Node instalados — tudo
roda nos containers.

---

## 2. Configurar o Google Drive (uma vez)

1. **Projeto + API:** no [Google Cloud Console](https://console.cloud.google.com/),
   crie/selecione um projeto e **ative a Google Drive API**.
2. **Service Account (SA):** *IAM & Admin → Service Accounts → Create*. Em
   **Keys → Add key → JSON**, baixe o arquivo (NUNCA comite).
3. **Pasta / Shared Drive privado:**
   - Crie a pasta (ou um **Shared Drive**, recomendado) que guardará os PDFs.
   - Compartilhe-a com o **e-mail da SA** (`...@...iam.gserviceaccount.com`) como
     **Editor / Gerente de conteúdo**.
   - Pegue o **ID** da URL: `.../folders/<ESTE_ID>`.
4. **Base64 do JSON** (para a variável de ambiente):
   ```bash
   base64 -w0 service-account.json
   ```
   O app usa apenas o escopo `drive.file` (mínimo privilégio): a SA só enxerga os
   arquivos que ela cria. Os PDFs **não** ficam públicos; o download sempre passa
   pelo backend (nenhum link do Drive chega ao navegador).

---

## 3. Preencher o `.env`

```bash
cp .env.docker.example .env
nano .env
```
Itens obrigatórios:

- `POSTGRES_PASSWORD` e o mesmo valor dentro de `DATABASE_URL`.
- `JWT_SECRET` e `DOCUMENT_HASH_SECRET` → `openssl rand -base64 48` (valores diferentes).
- `ADMIN_INITIAL_USERNAME` / `ADMIN_INITIAL_PASSWORD` (1º login da secretaria).
- `ADMIN_FRONTEND_URL=http://SEU_IP:8080` e `PUBLIC_VALIDATION_BASE_URL=http://SEU_IP`.
- `GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID` e `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64`.

> Na fase de teste mantenha `APP_ENV=development` e `AUTH_COOKIE_SECURE=false`
> (cookie funciona em HTTP). Mesmo assim os PDFs vão para o Drive, pois
> `STORAGE_PROVIDER=google_drive` é respeitado em qualquer ambiente.

---

## 4. Subir

```bash
docker compose build          # ~5–10 min na 1ª vez
docker compose up -d
docker compose ps             # admin/consulta/web/db = Up; migrate = Exited (0)
docker compose logs -f migrate    # deve mostrar 'upgrade ... 0005' + template padrão
```

Acessos:

| O quê | URL (teste) |
|---|---|
| Site público (alunos) | `http://SEU_IP/` |
| Validação por QR | `http://SEU_IP/validar/<codigo>` |
| Painel admin (React) | `http://SEU_IP:8080/` |
| Health | `http://SEU_IP:8080/api/health` e `http://SEU_IP/health` |

Login no admin com `ADMIN_INITIAL_USERNAME/PASSWORD`. Em **Template global**,
confirme que há uma versão **ativa** (a padrão é criada no `migrate`). Emita uma
planilha de teste (dados **sintéticos**) e confira o certificado na consulta.

---

## 5. Operação (cron no host)

Crie tarefas agendadas que executam comandos **dentro** do container admin:

```bash
crontab -e
```
```cron
# Backup do PostgreSQL (diário às 02h) — guarde fora do servidor também
0 2 * * * cd /caminho/certificados && docker compose exec -T db \
  pg_dump -U certuser certificados | gzip > backups/cert_$(date +\%F).sql.gz

# Integridade dos arquivos no Drive (diário 03h): bloqueia adulterados + audita
0 3 * * * cd /caminho/certificados && docker compose exec -T admin \
  python verify_integrity.py

# Reconciliação interna (de hora em hora): pending/órfãos
0 * * * * cd /caminho/certificados && docker compose exec -T admin \
  python reconcile.py

# Reconciliação Drive × banco (diário 04h): só ids/códigos, sem dados pessoais
0 4 * * * cd /caminho/certificados && docker compose exec -T admin \
  python reconcile_drive.py
```
Métricas em `GET /api/metrics` (admin, autenticado). Logs estruturados (JSON com
`correlation_id`): `docker compose logs -f admin`.

**Backup do banco é crítico:** o PostgreSQL é o mapa **código ↔ arquivo no Drive**.
Os PDFs estão no Drive (que tem sua própria redundância), mas sem o banco você
perde a ligação. Teste o restore (ver `docs/DEPLOY_E_RECUPERACAO.md`).

---

## 6. Dimensionamento (2 núcleos / 2–4 GB)

- **Workers:** comece com `ADMIN_WORKERS=1` e `CONSULTA_WORKERS=1`. Com 4 GB, pode
  subir `ADMIN_WORKERS=2`. Cada worker do admin carrega pandas/Pillow (~200–300 MB).
- **Orçamento de RAM (estimativa):** Postgres ~300 MB · admin ~300 MB · consulta
  ~120 MB · nginx ~20 MB · SO ~300 MB ≈ **~1,1 GB**. Cabe em 2 GB; **4 GB recomendado**.
- **Geração em lote:** é sequencial (1 PDF por vez), então a memória é por
  certificado e liberada em seguida; lotes grandes apenas demoram (CPU). O nginx
  já está com `proxy_read_timeout 600s` para o `/api`.
- **Imagem de template:** mantenha o fundo em ~A4 300 dpi (≈ 3508×2480). O app
  limita a 40 MP / 12000 px, mas imagens enormes consomem RAM ao renderizar — em
  2 GB, evite fundos gigantes.
- **PostgreSQL leve (opcional):** se a RAM ficar apertada, adicione no serviço
  `db`: `command: ["postgres","-c","shared_buffers=128MB","-c","max_connections=50"]`.
- **Disco:** com Drive, o disco guarda só o banco + imagens (no Postgres) + a
  própria imagem Docker (~600 MB–1 GB). 20–25 GB sobra com folga.

---

## 7. Migrar de TESTE (HTTP) para PRODUÇÃO (HTTPS, quando tiver domínio)

1. Aponte o domínio (ex.: `certificados.faculdade.edu`) para o IP do servidor.
2. **TLS automático (Let's Encrypt):** a forma mais simples é colocar um
   *companion* (ex.: `nginx-proxy` + `acme-companion`, ou Caddy) na frente, ou
   rodar `certbot` e montar os certificados no serviço `web`. No `deploy/nginx.conf`,
   troque `listen 80;`/`listen 8080;` por `listen 443 ssl;`/`listen 8443 ssl;`,
   adicione `ssl_certificate`/`ssl_certificate_key` e um `server` 80→443 de redirect.
3. **No `.env`:**
   - `APP_ENV=production` e **remova** `AUTH_COOKIE_SECURE` (passa a Secure sozinho).
   - `ADMIN_FRONTEND_URL=https://admin.seu-dominio` (ou o host:porta do admin em HTTPS).
   - `PUBLIC_VALIDATION_BASE_URL=https://seu-dominio` (precisa ser **HTTPS** em produção).
4. `docker compose build web && docker compose up -d` (rebuild do front para a
   nova URL, se mudou) e confirme o login (cookie Secure exige HTTPS).

> Em `APP_ENV=production` o app **falha ao iniciar** se faltar `DATABASE_URL`,
> `JWT_SECRET`, allowlist de CORS HTTPS, `PUBLIC_VALIDATION_BASE_URL` ou as
> credenciais do Drive — isso é proposital (fail-closed).

### Endurecer o admin (recomendado após os testes)
Mesmo “aberto”, vale restringir o painel à rede do campus: descomente o bloco
`allow/deny` em `deploy/nginx.conf` (location do `:8080`/`:8443`) com as faixas
de IP da faculdade. O login + cookie seguro continuam valendo de qualquer forma.

---

## 8. Fontes no Linux (observação)

A geração usa **Times New Roman** (arquivo já incluído no repo) — funciona no
Linux. O editor visual também oferece Arial/Georgia/Verdana/Courier, que no
Windows vêm do sistema; no Linux esses **caem automaticamente para o Times
incluído** (sem erro). O `Dockerfile` instala `fonts-liberation`/`fonts-dejavu`
como substitutos próximos. Se precisar de Arial idêntica, monte a fonte e ajuste
o mapa em `services/generator.py` (`_resolve_visual_font`).

---

## 9. Checklist e troubleshooting

**Checklist de subida**
- [ ] `.env` preenchido (senhas, segredos, IP, Drive folder + base64).
- [ ] `docker compose ps`: `migrate` saiu com código 0; demais `Up (healthy)`.
- [ ] Login admin OK; **Template global** com versão ativa.
- [ ] Emissão de teste (dados sintéticos) → aparece na consulta → download OK.
- [ ] Cron de backup + `verify_integrity` + `reconcile_drive` configurados.

**Problemas comuns**
- *Login não persiste:* em HTTP, garanta `AUTH_COOKIE_SECURE=false` e
  `APP_ENV=development`; em HTTPS, `APP_ENV=production` (cookie Secure exige TLS).
- *Erro ao salvar no Drive (502):* confira `GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID`,
  o base64 do JSON, e se a pasta foi compartilhada com o e-mail da SA. Veja
  `docker compose logs admin`.
- *Rate limit bloqueando você:* ajuste `TRUSTED_PROXY_CIDRS` para a sub-rede do
  compose (padrão `172.16.0.0/12`) para o IP real do cliente ser usado.
- *Admin chama a API errada:* o build do front embute `VITE_API_BASE_URL=/api`;
  se mudar, rode `docker compose build web`.
- *`migrate` falhou:* veja `docker compose logs migrate`; rode novamente
  `docker compose up -d migrate` (é idempotente).

Detalhes de arquitetura, backup/restore do PostgreSQL, permissões do Shared Drive
e rollback estão em [docs/DEPLOY_E_RECUPERACAO.md](DEPLOY_E_RECUPERACAO.md) e
[docs/ARQUITETURA.md](ARQUITETURA.md).
