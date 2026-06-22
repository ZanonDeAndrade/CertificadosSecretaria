# Deploy, backup e recuperação

## Pré-requisitos de produção

- PostgreSQL 13+ gerenciado (com backup automático).
- Pasta/Shared Drive privado no Google + Service Account(s).
- HTTPS em ambos os deploys; `admin` em rede interna/VPN, `consulta` exposta.

Em `APP_ENV=production` a aplicação **falha ao iniciar** se faltar `DATABASE_URL`,
`JWT_SECRET`, allowlist de CORS HTTPS, `PUBLIC_VALIDATION_BASE_URL`, a pasta do
Drive ou as credenciais; e `STORAGE_PROVIDER` precisa ser `google_drive`.

## Procedimento de deploy

1. **Provisione** o PostgreSQL e crie o banco; configure `DATABASE_URL`.
2. **Variáveis** (ver `.env.example`): `APP_ENV=production`, `JWT_SECRET`,
   `DOCUMENT_HASH_SECRET`, `ADMIN_FRONTEND_URL`/`CORS_ALLOWED_ORIGINS` (HTTPS),
   `PUBLIC_VALIDATION_BASE_URL` (HTTPS), `STORAGE_PROVIDER=google_drive`,
   `GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64`.
3. **Migrations** (uma vez por release, antes de subir):
   ```bash
   alembic upgrade head
   alembic current        # confirme a revisão (deve ser a head)
   ```
4. **Template padrão** (1º deploy): `python certificados-admin/backEnd/seed_template.py`.
5. **Suba** os processos (uvicorn atrás de nginx). Admin e consulta podem estar
   em hosts distintos apontando para o mesmo `DATABASE_URL` e o mesmo Drive.
6. **Healthcheck**: `GET /health` em cada serviço; métricas em `GET /metrics` (admin).
7. **Jobs agendados (cron)**:
   ```bash
   python verify_integrity.py     # integridade dos arquivos (ex.: diário)
   python reconcile.py            # pending/órfãos do banco (ex.: horário)
   python reconcile_drive.py      # Drive × banco, só ids/códigos (ex.: diário)
   ```

## Migração de PDFs existentes para o Drive (segura)

`migrate_to_drive.py` é **idempotente**, calcula **checksum**, tem **dry-run** e **relatório**:
```bash
cd certificados-admin/backEnd
python migrate_to_drive.py --dry-run     # simula; nada é enviado
python migrate_to_drive.py               # envia os pendentes (sem drive_file_id)
python migrate_to_drive.py --limit 100   # em lotes
```
Nunca reenvia quem já tem `drive_file_id`; mantém o `pdf_path` local como backup.

## Google Drive / Shared Drive — permissões mínimas

- **Escopo OAuth**: apenas `https://www.googleapis.com/auth/drive.file`
  (acesso restrito aos arquivos criados pelo app — menor privilégio).
- **Shared Drive (recomendado)**: crie um Shared Drive; adicione a Service
  Account do **admin** como **Gerente de conteúdo** (criar/excluir) e a SA da
  **consulta** como **Leitor**. Assim a consulta nunca recebe credenciais com
  escrita. Os arquivos **não** são públicos; o download é sempre proxiado pelo
  backend via `drive_file_id` — nenhum link/ID do Drive chega ao cliente.
- Forneça a credencial via `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` (nunca comite o JSON).

## Backup e restore do PostgreSQL

**Backup** (lógico, diário + retenção):
```bash
pg_dump --format=custom --no-owner --no-privileges \
  "$DATABASE_URL" > backup_$(date +%F).dump
```
**Restore** (banco limpo):
```bash
createdb certificados_restore
pg_restore --no-owner --no-privileges --dbjobs=4 \
  -d "postgresql://user:pass@host:5432/certificados_restore" backup_AAAA-MM-DD.dump
```
Recomendado também habilitar **PITR** (WAL archiving) ou snapshots do provedor.
O banco é o mapa **código ↔ arquivo no Drive**: após restaurar, rode
`python reconcile_drive.py` e `python verify_integrity.py` para confirmar a
consistência banco × Drive.

## Procedimento de rollback

1. **App**: reimplante a imagem/tag anterior dos serviços.
2. **Migrations**: cada migration tem `downgrade`. Para voltar uma versão:
   ```bash
   alembic downgrade -1     # ou: alembic downgrade <revisão alvo>
   ```
   > ⚠️ `downgrade` pode descartar colunas/constraints novas. Faça **backup
   > (pg_dump) antes** de qualquer downgrade de schema; prefira restaurar o dump
   > anterior se o downgrade implicar perda de dados.
3. **Template**: versões são imutáveis — para "voltar" o template, **ative** a
   versão anterior em *Histórico de versões* (nada é apagado).
4. **Arquivos no Drive**: a reemissão finaliza o novo arquivo **antes** de
   excluir o antigo e preserva o anterior em caso de falha — não há perda. Após
   um rollback de app, rode `reconcile_drive.py` para detectar órfãos (por id).

## Recuperação de incidentes

- **Arquivo adulterado/corrompido**: bloqueado automaticamente no download
  (`integrity_blocked`) + incidente em `audit_log`. Reemita pelo admin.
- **Geração interrompida**: `reconcile.py` resolve `pending` antigos e remove
  arquivos órfãos; `verify_integrity.py` revalida os ativos.
- **Drift Drive × banco**: `reconcile_drive.py` lista órfãos (por id) e
  certificados sem arquivo (por código), sem expor dados pessoais.
