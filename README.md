# CertificadosSecretaria

Sistema web para emissão, administração e validação pública de
certificados acadêmicos. A secretaria importa uma planilha `.xlsx`, revisa os
dados, confirma um lote idempotente e acompanha o processamento. Cada PDF recebe
código único e QR Code para a rota pública canônica.

O sistema atual usa:

- React 19, TypeScript 6 e Vite 8 no painel administrativo;
- FastAPI/Python 3.12 na API administrativa e na aplicação pública;
- PostgreSQL 16 em produção; SQLite somente para desenvolvimento e testes;
- Google Drive privado com uma pasta selecionada por evento via OAuth/Picker;
- Alembic para o schema, atualmente na migration `0011`;
- worker persistente com lease, retry e payload de lote cifrado;
- sessões revogáveis, RBAC (`admin`, `secretaria`, `auditor`) e auditoria.

Nenhuma implantação é realizada automaticamente por este repositório. O modo
local padrão usa recursos descartáveis e dados sintéticos.

## Componentes

| Caminho | Responsabilidade |
|---|---|
| `certificados-admin/frontend` | SPA administrativa. |
| `certificados-admin/backEnd` | API, autenticação, RBAC, lotes, PDFs, auditoria e jobs. |
| `certificados_consulta` | site/API públicos de busca, validação e download. |
| `database` | modelos, repositórios e migrations. |
| `storage_service` | storage local de desenvolvimento e Google Drive privado. |
| `observability` | logs estruturados, correlação e métricas. |
| `deploy` | imagens e configuração de execução; não executa deploy sozinho. |

## Início rápido para desenvolvimento

Pré-requisitos: Python 3.12.13, `uv` 0.12.3, Node.js 20.20.2 e npm
10.8.2. Os exemplos abaixo não usam credenciais reais.

```bash
uv sync --frozen --group dev
cp .env.example .env
uv run alembic upgrade head
uv run pytest -q

cd certificados-admin/frontend
npm ci --no-audit --no-fund
npm run typecheck
npm test
npm run build
```

Para executar a API administrativa e a consulta pública em desenvolvimento:

```bash
uv run uvicorn certificados_backend.main:app --host 127.0.0.1 --port 8000
uv run uvicorn certificados_consulta.app:app --host 127.0.0.1 --port 8001
```

O frontend pode ser iniciado, em outro terminal, com:

```bash
cd certificados-admin/frontend
npm run dev
```

Consulte o [manual de instalação](docs/MANUAL_INSTALACAO.md) para PostgreSQL,
worker, containers e configuração segura.

## Testes e qualidade

Os comandos canônicos e seus ambientes estão no
[plano de testes](docs/PLANO_TESTES.md) e no workflow
[`.github/workflows/ci.yml`](.github/workflows/ci.yml). Testes PostgreSQL usam
um banco descartável indicado por `TEST_DATABASE_URL`. E2E e screenshots usam
a API simulada versionada, com dados sintéticos, e não comprovam integração com
Google Drive real.

## Documentação canônica

- [Relatório técnico final](docs/RELATORIO_TECNICO_FINAL.md)
- [Relatório de prontidão](docs/RELATORIO_DE_PRONTIDAO_FINAL.md)
- [Arquitetura C4](docs/ARQUITETURA_C4.md)
- [Diagrama ER](docs/DIAGRAMA_ER.md)
- [Fluxos principais](docs/FLUXOS.md)
- [Modelo de ameaças](docs/MODELO_DE_AMEACAS.md)
- [Matriz de requisitos](docs/MATRIZ_DE_REQUISITOS.md)
- [Manual rápido da secretaria](docs/MANUAL_SECRETARIA.md)
- [Ambientes de desenvolvimento e LAN](docs/ENVIRONMENTS.md)
- [Google Drive e OAuth](docs/GOOGLE_DRIVE.md)
- [Servidor local](docs/LOCAL_SERVER.md)
- [Contrato da planilha](docs/CONTRATO_PLANILHA.md)
- [Política de segurança e LGPD](docs/POLITICA_SEGURANCA_LGPD.md)
- [Backup e recuperação](docs/PLANO_BACKUP_RECUPERACAO.md)
- [Limitações e trabalhos futuros](docs/LIMITACOES_TRABALHOS_FUTUROS.md)

Documentos anteriores foram preservados em `docs/historico/` e estão
explicitamente marcados como históricos/obsoletos. Eles não descrevem o sistema
atual.

## Segurança da entrega

Nunca adicione `.env`, banco, planilha de participantes, PDF nominal, token,
credencial ou log ao Git. O ZIP acadêmico é produzido somente de um checkout
limpo por `python -m scripts.export_release` e verificado por
`python -m scripts.security_scan --artifact`.
