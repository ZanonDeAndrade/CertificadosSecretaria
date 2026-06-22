# Arquitetura — CertificadosSecretaria

Dois deploys independentes sobre **um PostgreSQL** e **um Google Drive privado**.

```
                         ┌─────────────────────────┐
  Secretaria  ──HTTPS──▶ │ certificados-admin      │
  (rede interna/VPN)     │  FastAPI + React (Vite) │──┐
                         └─────────────────────────┘  │
                                                       │   ┌────────────────┐
  Aluno  ──────HTTPS───▶ ┌─────────────────────────┐  ├──▶│  PostgreSQL    │ (metadados)
  (internet)             │ certificados-consulta   │──┘   └────────────────┘
                         │  FastAPI + Jinja2        │      ┌────────────────┐
                         └─────────────────────────┘─────▶│ Google Drive   │ (PDFs privados)
                                                          └────────────────┘
```

## Componentes

| Pacote | Responsabilidade |
|---|---|
| `certificados-admin/backEnd` | API da secretaria: emissão (saga), histórico, revogação, reemissão, template global, integridade, downloads. |
| `certificados-admin/frontend` | React + Vite + Tailwind; editor visual (fabric.js, **lazy-loaded**). |
| `certificados-consulta` | Site público (Jinja2): busca por nome/código, validação, download proxiado. |
| `database/` | SQLAlchemy: `config` (DATABASE_URL/pool), `engine` (sessões/transações), `models` (schema), `repositories` (todo o SQL), `db` (fachada), `migrations` (Alembic). |
| `storage_service/` | Abstração `local`/`google_drive`: `save`/`download`/`delete`, verificação de integridade, dispatcher sem expor link/credencial ao cliente. |
| `observability/` | Logs JSON estruturados, `correlation_id` por requisição, métricas em processo. Compartilhado pelos dois apps; **sem PII**. |

## Persistência

- **PostgreSQL** em produção (via `DATABASE_URL`); **SQLite** apenas em dev/teste.
- O banco guarda **somente metadados** — o PDF nunca é gravado no banco.
- Camada de **repositórios** (sem SQL nas rotas) com **pool** e **transações**.
- Schema versionado por **Alembic** (`0001`…`0005`). Modelos ORM são a fonte de verdade.
- Datas (`issue_date`/`start_date`/`end_date`) em **ISO `YYYY-MM-DD`** (índice em `issue_date`); "por extenso" só na apresentação.
- **Constraints**: `CHECK` em `status`/`role`/`storage_provider`; **FKs** `issued_by`/`revoked_by`/`audit_log.actor_id` → `admin_users` com **`ON DELETE SET NULL`** (auditoria preservada).

## Fluxo de emissão (saga + compensação)

Como uma transação ACID não abrange PostgreSQL + Drive, cada certificado segue uma saga:

1. **Reserva** (transação): `business_key` + código aleatório, `INSERT` `pending` garantido por constraints `UNIQUE` (sem `INSERT OR IGNORE`); colisão de código → novo código; colisão de `business_key` → duplicado.
2. **Upload**: renderiza o PDF (template global ativo) em memória e envia ao Drive.
3. **Finalização** (transação): grava `drive_file_id` + `checksum` + `file_size`, status `ativo`.
4. **Falha**: marca `failed`, **exclui o arquivo** enviado (se a finalização falhou), audita; nunca reporta sucesso.

Reparos assíncronos: `reconcile.py` (pending antigos / ativo sem arquivo / failed com órfão), `verify_integrity.py` (integridade periódica), `reconcile_drive.py` (Drive×banco, só ids/códigos).

## Template global

Um único template global versionado e imutável; uma versão **ativa** por vez (ativação explícita). Cada certificado grava `template_version_id` + `template_snapshot` (reemissão fiel). Imagem de fundo durável no banco (BYTEA), nunca em APPDATA/JSON local.

## Integridade e segurança de arquivos

- Todo download verifica **PDF + tamanho + SHA-256**; divergência → bloqueia (`integrity_blocked`), audita incidente, não entrega.
- Storage local rejeita caminhos absolutos e `..`.
- Uploads de planilha: validação OOXML real + limites (linhas/colunas/célula/tempo) e guarda anti-bomba **antes** de carregar; imagens com `Image.verify()` + limites de pixels/dimensão; template limita elementos e data URLs.

## Observabilidade

- Logs **JSON** com `ts`, `level`, `logger`, `msg`, `correlation_id` (cabeçalho `X-Request-ID` propagado).
- Métricas em `GET /metrics` (admin): `certificates_generated_total`, `_duplicate_total`, `_failed_total`, `_compensated_total`, `certificate_downloads_total`, `integrity_incidents_total`.
- **Nunca** logamos nome/documento/e-mail; o middleware registra só `method`/`path`/`status`/`duration_ms` (sem query string).
