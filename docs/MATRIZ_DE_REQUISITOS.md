# Matriz de requisitos

Status reflete o código candidato; a aprovação final depende do relatório de
prontidão. “Coberto” significa que existe teste automatizado localizado, não que
o comportamento já foi comprovado em produção.

## Funcionais

| ID | Requisito | Status no código | Evidência principal |
|---|---|---|---|
| RF01 | login, logout e sessão revogável | implementado/coberto | `auth.py`, `routers/auth.py`, `test_auth.py`. |
| RF02 | RBAC admin/secretaria/auditor | implementado/coberto, inclusive negativo | `policies.py`, `test_functional_phase.py`, E2E de perfis. |
| RF03 | gestão de usuários e troca obrigatória de senha | implementado/coberto | `routers/users.py`, testes de usuário e frontend. |
| RF04 | importar e pré-validar `.xlsx` | implementado/coberto | `spreadsheet.py`, `test_spreadsheet.py`. |
| RF05 | preview e confirmação antes de emitir | implementado/coberto | página Emitir, testes frontend/E2E. |
| RF06 | lote idempotente e retomável | implementado/coberto | batches, migrations `0008`/`0009`, testes de job e PostgreSQL. |
| RF07 | PDF com código único e QR | implementado/coberto | generator/certificate service, testes de geração. |
| RF08 | Drive privado, OAuth/Picker e pasta por evento | implementado; integração real não executada | drive integration, storage e testes com fakes. |
| RF09 | histórico, filtros e detalhe | implementado/coberto | página Histórico, API e E2E. |
| RF10 | download individual e ZIP | implementado/coberto | routers/certificates, testes admin/E2E. |
| RF11 | revogação com motivo e bloqueio público | implementado/coberto | management/public tests. |
| RF12 | reemissão com snapshots imutáveis | implementado/coberto | certificate management/service, testes de saga/templates. |
| RF13 | template global versionado e ativação exclusiva | implementado/coberto | template service, teste de concorrência PostgreSQL. |
| RF14 | validação pública canônica pelo QR | implementado/coberto | `/validar/{code}`, testes públicos/QR. |
| RF15 | busca nominal minimizada + confirmação | implementado/coberto | app pública, privacy tests. |
| RF16 | auditoria consultável e minimizada | implementado/coberto | audit service/router, testes e E2E. |
| RF17 | configuração institucional sem segredos | implementado/coberto | settings service/schema e testes. |
| RF18 | backup cifrado, verificação e restore drill | implementado/coberto em unitário; drill final no relatório | `backup.py`, `test_backup.py`. |

## Não funcionais

| ID | Requisito | Critério | Implementação/verificação |
|---|---|---|---|
| RNF01 | segurança | nenhuma vulnerabilidade alta/crítica conhecida | dependency audits, scanner de imagem e relatório final. |
| RNF02 | privacidade | nenhuma PII/segredo no Git/ZIP; respostas públicas minimizadas | scanner, teste de release, testes de privacidade. |
| RNF03 | integridade | PDF divergente não é servido | SHA-256/tamanho/assinatura e testes negativos. |
| RNF04 | consistência | retry e concorrência não duplicam emissão | constraints + testes PostgreSQL. |
| RNF05 | durabilidade | job retomável após lease expirar e conserva destinos | migrations `0008`/`0009`, worker e testes conectados. |
| RNF06 | acessibilidade | fluxos principais sem violação axe no conjunto testado | Playwright/axe; não equivale a auditoria WCAG completa. |
| RNF07 | reprodutibilidade | instalação bloqueada e build determinístico | `uv.lock`, hashes, `npm ci`, wheel repetido. |
| RNF08 | portabilidade | containers sem root e read-only onde testado | Dockerfiles e smoke de imagem. |
| RNF09 | observabilidade | health/readiness, correlação e logs estruturados | endpoints, middleware e testes. |
| RNF10 | recuperação | backup restaurado em PostgreSQL descartável | drill exigido antes da saída. |
| RNF11 | desempenho defensivo | limites de upload/lote/célula e contratos de carga limitados | settings, spreadsheet guards, `test_load_contracts.py`; sem benchmark de produção. |
| RNF12 | manutenibilidade | lint, format, tipos, migrations sem drift | Ruff, mypy e Alembic no CI/auditoria. |

## Fora de escopo confirmado

MFA/SSO, assinatura digital ICP-Brasil, envio de certificado por e-mail, aplicativo
móvel nativo, integração com sistema acadêmico, OCR e SLA de produção não estão
implementados.
