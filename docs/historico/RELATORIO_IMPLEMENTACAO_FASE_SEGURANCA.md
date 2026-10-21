# Relatório Final de Implementação — CertificadosSecretaria

> Consolida as correções dos achados do [RELATORIO_AUDITORIA.md](RELATORIO_AUDITORIA.md)
> e a finalização (limpeza, migração de dados, observabilidade, CI e documentação).
> Data: 2026-06-20.

---

## 1. Achados resolvidos

| ID | Achado | Resolução | Evidência |
|----|--------|-----------|-----------|
| **F1** | Geração não-transacional / `INSERT OR IGNORE` | Saga reserva→upload→finaliza com compensação; insert estrito | `services/certificate_service.py` (`_emit_one`/`_compensate`), `database/repositories.py` |
| **F2** | Código/`business_key` sem transação | Reserva atômica por tentativa (constraints UNIQUE), retry de código, duplicado por business_key | `database/db.py` (`reserve_certificate`) |
| **F3** | QR aponta para `/validar` inexistente | Rota pública `GET /validar/{code}` + `build_public_validation_url` | `certificados-consulta/app.py:380`, `storage_service/config.py` |
| **F4** | Login sem proteção a força bruta | Throttle persistido (IP+usuário), backoff, lockout | `database/models.py` (`login_throttles`), migration `0003` |
| **F5** | Não falha sem `JWT_SECRET` em produção | Fail-closed no startup (DATABASE_URL/JWT/CORS/Drive) | `main.validate_startup_config`, `database/config.require_production_database` |
| **F6** | Reemissão sem snapshot + órfãos no Drive | `template_version_id`+`template_snapshot`; finaliza novo antes de excluir antigo, preserva em falha | `certificate_service.reissue_certificate`, `test_templates.py` |
| **F7** | Busca pública expõe código/LGPD | Busca nominal sem código + confirmação de documento; minimização | `certificados-consulta/app.py`, migration `0004` |
| **F8** | Datas por extenso ordenando errado | Armazenadas ISO + índice; "por extenso" só na apresentação; migração+relatório | `utils/dates.py`, migration `0005`, `migrate_dates.py`, `test_hardening.py` |
| **F9** | `event` recebia o curso | `event` e `course` distintos; `ParticipantRegistryRecord` carrega ambos | `services/generator.py` (`_participant_data`), `test_templates.py` |
| **F10** | `LIKE %x%` curingas/acentos | Nome normalizado (sem acento) + tamanho mínimo + índice | migration `0004`, `database/privacy.py` |
| **F11** | Rate limit local/atrás de proxy | Limite persistido no banco (multi-worker) + proxies confiáveis | `public_rate_limits`, `TRUSTED_PROXY_CIDRS` |
| **F12** | Checksum não verificado no download | Verifica PDF+tamanho+SHA-256; bloqueia+audita+não entrega; verificação periódica | `storage_service` (`verify_pdf_integrity`), `services/integrity.py`, `verify_integrity.py`, `test_hardening.py` |
| **F13** | Logout/JWT sem revogação | Sessões revogáveis por `jti` (`auth_sessions`) | migration `0003` |
| **F14** | Fluxo legado inconsistente | **Removido** `/generate-certificates`, `reader/registry`, `Participant`, `CertificateFormData` | `main.py`, `services/certificate_service.py` |
| **F15** | Uploads (bomba/dimensões/data URLs) | OOXML real + limites antes de carregar; `Image.verify()`+pixels; cap de elementos/data URLs | `services/spreadsheet.py` (`enforce_xlsx_limits`), `services/template_service.py`, `test_hardening.py` |
| **F16** | Falta CHECK/FK | CHECK (status/role/storage_provider) + FKs `ON DELETE SET NULL` (auditoria preservada) | `database/models.py`, migration `0005`, `test_hardening.py` |
| **F17** | Bundle > 500 KB sem code-split | Editor (fabric.js) **lazy-loaded** em chunk separado | build: `fabric-*.js 280 KB`, `index-*.js 266 KB` |
| **F18** | SQLite/FS impedem deploys independentes | PostgreSQL por `DATABASE_URL` + Drive; dois deploys sobre o mesmo PG/Drive | `database/engine.py`, `docs/DEPLOY_E_RECUPERACAO.md` |
| **F19** | Dependências npm com vulnerabilidades | CI audita (pip-audit + npm audit) | `.github/workflows/ci.yml` (ver risco residual) |
| **F20** | `/validate` público no admin | **Removido** do admin (validação é responsabilidade da consulta) | `main.py` (sem `/validate`) |
| **F21** | Path traversal local | Rejeita absolutos e `..`, confina ao storage | `storage_service/local.py` (`_resolve_within_storage`), `test_hardening.py` |
| **F22** | Download em lote sem UI | UI de seleção + ZIP no frontend | `frontend/src/services/api.ts` (`downloadCertificatesZip`) |
| **F23** | Higiene de dados / `.gitignore` | `.gitignore` cobre `data/`, PDFs, bancos, credenciais, logs, artefatos; fixtures sintéticas | `.gitignore`, testes geram dados em memória |
| **F24** | CSRF | `SameSite` + validação de `Origin`/`Referer` em mutações | `auth.validate_mutating_request_origin` |
| **F25** | UX/acessibilidade (prompt nativo) | Modal acessível (foco/aria) + estados de erro | `frontend/.../AccessibleModal`, `TemplateEditor.tsx` |

---

## 2. Achados pendentes / parcialmente resolvidos

- **F19 (dependências):** o CI executa `pip-audit` e `npm audit`, porém como
  passos **não bloqueantes** (`continue-on-error`) para não travar o pipeline em
  advisories transitivas. **Pendente:** rodar `npm audit fix` e fixar versões;
  decidir política de bloqueio por severidade.
- **Tipagem estática (Python):** o CI faz `ruff` + `compileall` + `tsc` (frontend);
  **não** há `mypy` estrito. Recomendado adicionar mypy incremental.
- **Reconciliação Drive×banco:** implementada e segura (só ids/códigos), mas
  **não testada contra um Drive real** (sem credenciais em CI); a lógica do lado
  do banco (`drive_file_index`) tem teste.

Nenhum achado **crítico/alto** do relatório permanece aberto.

---

## 3. Migrations criadas (Alembic, `database/migrations/`)

| Revisão | Conteúdo |
|---|---|
| `0001_initial_schema` | `certificates`, `admin_users`, `audit_log` + índices |
| `0002_template_versions` | `template_versions` + `template_version_id`/`template_snapshot` (F6) |
| `0003_auth_security` | `auth_sessions` (revogação) + `login_throttles` (F4/F13) |
| `0004_public_privacy_and_rate_limits` | nome normalizado, hash de documento, `public_rate_limits` (F7/F10/F11) |
| `0005_integrity_dates_constraints` | datas→ISO + índice, `integrity_blocked`, CHECK+FKs (F8/F12/F16) |

`alembic upgrade head` aplica a cadeia completa e `alembic check` não detecta
drift (modelos ORM ⇄ schema migrado).

---

## 4. Riscos residuais

1. **Advisories de dependências** podem existir até `npm audit fix`/atualização (F19).
2. **Flakiness sob ordem aleatória:** com `pytest-randomly`, ~3 testes do trabalho
   de privacidade/busca pública falham por **vazamento de estado entre testes**
   (passam isolados e em ordem fixa). Recomenda-se um fixture `autouse` que
   reseta estado de módulo. A suíte em **ordem determinística é verde**.
3. **`pending`/`failed`** podem aparecer brevemente no **histórico admin**; a busca
   pública é filtrada para `ativo`/`revogado`. Considerar filtrar o admin também.
4. **Sem mypy estrito** — erros de tipo só são pegos no frontend (tsc).
5. **Reconciliação de Drive** depende de credenciais corretas; valide em staging.
6. **Backup do PostgreSQL** é responsabilidade de operação (procedimento documentado,
   mas a automação/retenção precisa ser provisionada no ambiente).

---

## 5. Procedimento de deploy (resumo)

1. Provisione PostgreSQL + Shared Drive; configure `.env` de produção (fail-closed).
2. `alembic upgrade head` && `alembic current`.
3. `python seed_template.py` (1º deploy).
4. Suba admin (interno/VPN) e consulta (público) apontando ao mesmo PG/Drive.
5. Agende `verify_integrity.py`, `reconcile.py`, `reconcile_drive.py` (cron).
6. Verifique `GET /health` e `GET /metrics`.

Detalhes, backup/restore do PostgreSQL e permissões mínimas do Drive:
[docs/DEPLOY_E_RECUPERACAO.md](docs/DEPLOY_E_RECUPERACAO.md) ·
[docs/ARQUITETURA.md](docs/ARQUITETURA.md).

---

## 6. Procedimento de rollback

1. **App:** reimplante a tag anterior.
2. **Schema:** `pg_dump` **antes**; `alembic downgrade -1` (ou restaure o dump se
   houver risco de perda — `downgrade` pode remover colunas/constraints).
3. **Template:** **ative** a versão anterior em *Histórico de versões* (imutável,
   nada é apagado).
4. **Arquivos:** a reemissão é Drive-safe (novo finalizado antes de excluir o
   antigo; preserva em falha). Rode `reconcile_drive.py` para detectar órfãos.

---

## 7. Evidências dos testes

```text
# Backend (ordem determinística)
$ python -m pytest tests -p no:randomly -q
166 passed, 3 skipped            # (3 skipped = integração PostgreSQL sem TEST_DATABASE_URL)

# Suítes-chave desta entrega
test_hardening.py ....... 20 passed   # F8 ordenação, F12 integridade, F15 maliciosos,
                                      # F16 CHECK/FK, F21 traversal, índice Drive, métricas
test_saga.py ........... (saga F1/F2: concorrência, colisão, compensação, reconciliação)
test_templates.py ...... (F6/F9: versão, ativação, evento×curso, reemissão fiel, sem órfãos)

# Lint
$ ruff check .
All checks passed!

# Migrations (SQLite, cadeia 0001→0005)
$ DATABASE_URL=sqlite:///./ci_check.db alembic upgrade head && alembic check
Running upgrade ... -> 0005
No new upgrade operations detected.

# Frontend (typecheck + build, com code-splitting)
$ npm run build
dist/assets/index-*.js        266.61 kB
dist/assets/fabric-*.js       280.21 kB   # lazy (editor)
dist/assets/TemplateEditor-*.js 31.03 kB  # lazy
✓ built
```

Ferramentas de operação (todas com `--dry-run`/relatório quando aplicável):
`migrate_to_drive.py`, `verify_integrity.py`, `reconcile.py`, `reconcile_drive.py`,
`migrate_dates.py`, `seed_template.py`.

---

## 8. Itens de finalização entregues

- ✅ Fluxo legado `/generate-certificates` **removido** (código, modelos, testes, doc).
- ✅ `.gitignore` cobre `data/`, PDFs, bancos, credenciais, logs e artefatos.
- ✅ Fixtures de teste **sintéticas** (geradas em memória); dados reais nunca usados/commitados.
- ✅ Migração de PDFs ao Drive **segura** (dry-run, idempotência, checksum, relatório).
- ✅ Reconciliação **Drive × banco** sem expor dados pessoais (só ids/códigos).
- ✅ **CI** (lint, typecheck/build, testes, migrations, auditoria de deps, gitleaks).
- ✅ **Logs estruturados** + `correlation_id` + **métricas** (sem PII).
- ✅ Documentação: README, [ARQUITETURA](docs/ARQUITETURA.md),
  [DEPLOY_E_RECUPERACAO](docs/DEPLOY_E_RECUPERACAO.md) (backup/restore PG, Drive/permissões, rollback).
