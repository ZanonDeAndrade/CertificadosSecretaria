# Plano de testes

Objetivo: bloquear a entrega quando instalação, migration, fluxo crítico,
segurança, backup/restore ou controle de acesso falhar.

## Pirâmide e ambientes

| Camada | Escopo | Ambiente |
|---|---|---|
| estático | Ruff, format, mypy, TypeScript, lock drift | checkout limpo. |
| unitário | regras, schemas, criptografia, PDF, planilha, UI | SQLite/fakes e jsdom. |
| integração | API, repositórios, migrations, concorrência/jobs | PostgreSQL 16 descartável. |
| E2E | perfis e navegação responsiva | build real + API mock sintética fiel ao contrato. |
| acessibilidade | axe, teclado, landmarks e estados | Playwright desktop/mobile. |
| operação | containers, health, backup/restore, smoke | Docker e PostgreSQL descartável. |
| segurança | segredos, dependências, imagem, config, ZIP | scanners redigidos e audits. |

## Comandos canônicos

```bash
uv sync --frozen --group dev
uv lock --check
uv run ruff check certificados-admin/backEnd certificados_consulta database observability storage_service scripts
uv run ruff format --check certificados-admin/backEnd certificados_consulta database observability storage_service scripts
uv run mypy certificados-admin/backEnd certificados_consulta database observability storage_service scripts
uv run pytest -q

cd certificados-admin/frontend
npm ci --no-audit --no-fund
npm run typecheck
npm test
npm run build
npm run test:e2e
npm run test:a11y
npm audit --audit-level=high
```

Com `DATABASE_URL` e `TEST_DATABASE_URL` apontando para PostgreSQL descartável:

```bash
uv run alembic upgrade head
uv run alembic check
uv run alembic downgrade 0007
uv run alembic upgrade head
uv run pytest certificados-admin/backEnd/tests/test_integration_postgres.py certificados-admin/backEnd/tests/test_durable_jobs.py certificados-admin/backEnd/tests/test_template_concurrency.py -q
```

Dependências e release:

```bash
uv run pip-audit --requirement requirements/dev.txt --disable-pip
uv run pip-audit --requirement requirements/ops.txt --disable-pip
python -m scripts.security_scan --repository --permissions --history
python -m scripts.export_release /tmp/certificados-release.zip
python -m scripts.security_scan --artifact /tmp/certificados-release.zip
```

Containers devem ser construídos nos três targets, executados sem root/read-only
no smoke aplicável e escaneados por Trivy com `HIGH,CRITICAL` bloqueante. A
configuração de infraestrutura também deve ser escaneada.

## Casos críticos obrigatórios

- login inválido, bloqueio e sessão revogada;
- papel desconhecido sem permissão;
- secretaria/auditor tentando operação proibida (`403`);
- planilha inválida/oversized sem persistência;
- lote repetido igual e chave repetida conflitante;
- concorrência e retomada de job após lease;
- falha Drive com compensação/reconciliação;
- download revogado, ausente e checksum divergente;
- busca nominal sem vazamento de código e confirmação genérica;
- template concorrente e reemissão com snapshot;
- backup adulterado rejeitado e restore em alvo não descartável bloqueado;
- QR gerado aponta para rota pública existente;
- ZIP sem `.git`, dependências, cache, banco, planilha, PDF nominal, log ou secret.

## Critérios de aceitação

Zero falha nos casos críticos; zero vulnerabilidade alta/crítica conhecida;
zero segredo/PII no artefato; migrations e restore validados; build e instalação
limpa aprovados. Skip condicional precisa de justificativa e sua categoria
crítica deve ser executada no ambiente adequado antes da saída.

## Limite do plano

Os E2E atuais usam API mock e não são teste de navegador contra Drive real. Axe
não prova conformidade WCAG completa. Testes de carga são contratos limitados,
não benchmark/SLA de produção.
