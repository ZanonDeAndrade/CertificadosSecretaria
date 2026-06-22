# Certificados Secretaria

Plataforma web para **emitir, administrar, validar e baixar certificados
acadêmicos**. A secretaria importa uma planilha, revisa os dados, gera PDFs com
código único e QR Code e acompanha o histórico. O aluno usa uma área pública
para verificar a autenticidade do certificado e, quando autorizado, baixar o
arquivo.

O sistema é composto por um painel administrativo em React, duas aplicações
FastAPI, um PostgreSQL compartilhado e uma camada de arquivos que usa Google
Drive privado em produção.

> **Resumo:** os dados e metadados ficam no PostgreSQL; os PDFs definitivos
> ficam no Google Drive; credenciais de produção ficam no Google Secret Manager.
> O navegador nunca recebe credenciais ou links internos do Drive.

## Sumário

- [Funcionalidades](#funcionalidades)
- [Arquitetura](#arquitetura)
- [Tecnologias](#tecnologias)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Persistência](#persistência)
- [Fluxos principais](#fluxos-principais)
- [Segurança e privacidade](#segurança-e-privacidade)
- [Executar localmente](#executar-localmente)
- [Executar com Docker](#executar-com-docker)
- [Configuração](#configuração)
- [Google Drive](#google-drive)
- [Banco e migrations](#banco-e-migrations)
- [API](#api)
- [Testes e qualidade](#testes-e-qualidade)
- [Operação e observabilidade](#operação-e-observabilidade)
- [Deploy em produção](#deploy-em-produção)
- [Documentação complementar](#documentação-complementar)

## Funcionalidades

### Secretaria

- Login administrativo com sessão revogável no servidor.
- Perfis de acesso `admin`, `secretaria` e `auditor`.
- Importação de planilhas Excel `.xlsx`.
- Validação prévia da planilha, sem persistir ou gerar arquivos.
- Separação entre linhas válidas e inválidas, com motivo por linha.
- Geração em lote somente das linhas válidas.
- Código público único no formato `CERT-ANO-XXXXXX`.
- QR Code apontando para a página oficial de validação.
- Histórico com busca e filtros por nome, código, curso, evento e status.
- Download individual ou em ZIP, com limite e relatório de arquivos ignorados.
- Revogação com motivo obrigatório e preservação da rastreabilidade.
- Reemissão segura, mantendo o mesmo código e o template original.
- Visualização de metadados e estado de integridade do arquivo.
- Editor visual do template global.
- Versionamento imutável de templates e ativação explícita de uma versão.
- Registro de ações relevantes em trilha de auditoria.
- Métricas operacionais da API administrativa.

### Alunos e público externo

- Validação por código único.
- Página canônica acessível pelo QR Code.
- Busca nominal normalizada, sem diferenciar maiúsculas ou acentos.
- Consulta do estado: ativo, revogado ou inexistente.
- Download de certificado ativo sem expor o Google Drive.
- Confirmação por documento ou matrícula após busca nominal.
- Respostas públicas minimizadas, sem e-mail, documento ou IDs internos.
- Bloqueio de download para certificados revogados ou com falha de integridade.

### Administração e manutenção

- Migrations versionadas com Alembic.
- Reconciliação entre banco e Google Drive.
- Reparação de emissões interrompidas.
- Verificação periódica de integridade dos PDFs.
- Migração de PDFs locais antigos para o Drive.
- Migração de datas legadas para o padrão ISO.
- Health checks de processo e prontidão.
- Logs JSON com identificador de correlação.

## Arquitetura

```text
                         ┌──────────────────────────┐
 Secretaria ──HTTPS────▶ │ Painel administrativo    │
                         │ React + TypeScript        │
                         └────────────┬─────────────┘
                                      │ /api
                                      ▼
                         ┌──────────────────────────┐
                         │ API administrativa       │
                         │ FastAPI + Python         │
                         └────────┬─────────┬───────┘
                                  │         │
                                  │         └──────────────┐
                                  ▼                        ▼
                         ┌────────────────┐       ┌─────────────────┐
                         │ PostgreSQL     │       │ Google Drive     │
                         │ metadados      │       │ PDFs privados    │
                         └───────▲────────┘       └────────▲────────┘
                                 │                         │
                         ┌───────┴─────────────────────────┴───────┐
 Aluno ─────HTTPS──────▶ │ Consulta pública                       │
                         │ FastAPI + Jinja2                        │
                         └─────────────────────────────────────────┘
```

### Componentes

| Componente | Responsabilidade |
|---|---|
| `certificados-admin/frontend` | SPA administrativa, emissão, histórico e editor visual. |
| `certificados-admin/backEnd` | Autenticação, regras de negócio, geração, templates, auditoria e operações administrativas. |
| `certificados-consulta` | Site e API públicos de busca, validação e download. |
| `database` | Modelos ORM, engine, transações, repositórios e migrations. |
| `storage_service` | Interface comum para armazenamento local ou Google Drive. |
| `observability` | Logs estruturados, `correlation_id` e métricas. |
| `deploy` | Containers, Nginx, Caddy e automação de deploy. |

### Decisões arquiteturais

- **Dois backends independentes:** a área administrativa e a pública podem
  escalar e ser implantadas separadamente.
- **Banco compartilhado:** as duas aplicações consultam o mesmo PostgreSQL.
- **Arquivos fora do banco:** PDFs não ocupam o banco; apenas IDs e metadados
  necessários para recuperá-los são persistidos.
- **Storage abstrato:** regras de negócio não dependem diretamente do Drive.
- **Repositórios:** as rotas não espalham SQL; o acesso passa pela camada de
  persistência.
- **Saga de emissão:** PostgreSQL e Drive não participam da mesma transação
  ACID, portanto o sistema usa etapas e compensações explícitas.
- **Falha fechada em produção:** configurações inseguras ou ausentes impedem o
  início da aplicação.

## Tecnologias

### Frontend administrativo

| Tecnologia | Uso |
|---|---|
| React 19 | Interface e componentes do painel. |
| TypeScript 6 | Tipagem estática do frontend. |
| Vite 8 | Servidor de desenvolvimento e build. |
| Tailwind CSS 4 | Estilos e composição visual. |
| Axios | Comunicação HTTP com as APIs. |
| Fabric.js 7 | Canvas do editor visual de templates. |
| Vitest | Testes unitários do frontend. |
| Testing Library | Testes de interação e acessibilidade. |

O editor e o Fabric.js são carregados sob demanda com `React.lazy`, reduzindo o
JavaScript inicial do painel.

### Backend e dados

| Tecnologia/biblioteca | Uso |
|---|---|
| Python 3.11+ | Linguagem dos backends e utilitários. |
| FastAPI | APIs administrativa e pública. |
| Uvicorn | Servidor ASGI. |
| Pydantic | Validação dos contratos da API. |
| Jinja2 | Renderização do site público. |
| SQLAlchemy 2 | ORM, sessões, transações e consultas. |
| Alembic | Versionamento do schema. |
| psycopg 3 | Driver PostgreSQL. |
| Pandas | Normalização e processamento tabular. |
| OpenPyXL | Leitura segura e validada de `.xlsx`. |
| Pillow | Composição de imagens e geração do PDF. |
| qrcode | QR Code de validação. |
| bcrypt | Hash de senhas. |
| PyJWT | Tokens de sessão assinados. |
| Google API Client | Upload e download no Google Drive. |
| google-auth / oauthlib | Autenticação com o Google. |

### Infraestrutura e qualidade

| Tecnologia | Uso |
|---|---|
| PostgreSQL | Persistência principal de produção. |
| SQLite | Desenvolvimento e testes sem PostgreSQL. |
| Google Drive API | Armazenamento privado dos PDFs. |
| Google Cloud Run | Hospedagem dos três serviços web. |
| Google Secret Manager | Entrega de segredos aos containers. |
| Google Cloud Build | Build das imagens de produção. |
| Artifact Registry | Registro das imagens Docker. |
| Docker / Docker Compose | Empacotamento e ambientes locais/alternativos. |
| Nginx | Serviço do frontend e proxy no Cloud Run. |
| Caddy | TLS e gateway na alternativa com Compose. |
| GitHub Actions | CI de backend, frontend, migrations e segurança. |
| Ruff | Análise estática do Python. |
| Pytest | Testes do backend. |
| pip-audit / npm audit | Auditoria de dependências. |
| Gitleaks | Detecção de segredos no histórico Git. |

## Estrutura do projeto

```text
CertificadosSecretaria/
├── certificados-admin/
│   ├── backEnd/
│   │   ├── main.py                 # API administrativa
│   │   ├── auth.py                 # login, JWT, cookie e papéis
│   │   ├── services/               # emissão, PDF, template e integridade
│   │   ├── tests/                  # testes Pytest
│   │   ├── templates/              # modelo inicial
│   │   └── requirements.txt
│   └── frontend/
│       ├── src/                    # aplicação React
│       ├── package.json
│       └── vite.config.ts
├── certificados-consulta/
│   ├── app.py                      # site/API pública
│   ├── templates/                  # páginas Jinja2
│   ├── static/                     # CSS público
│   └── requirements.txt
├── database/
│   ├── models.py                   # fonte de verdade do schema
│   ├── repositories.py             # consultas e persistência
│   ├── engine.py                   # engine, pool e transações
│   ├── db.py                       # fachada compartilhada
│   └── migrations/                 # revisões Alembic
├── storage_service/
│   ├── base.py                     # contrato de armazenamento
│   ├── local.py                    # filesystem para desenvolvimento
│   └── google_drive.py             # Drive para produção
├── observability/                  # logs e métricas
├── deploy/
│   ├── cloudrun/                   # scripts do Cloud Run
│   ├── Dockerfile.web              # painel para Compose
│   └── Dockerfile.cloudrun-web     # painel para Cloud Run
├── docs/                           # arquitetura, deploy e recuperação
├── storage/pdfs/                   # PDFs locais de desenvolvimento
├── .env.example                    # referência completa de configuração
├── alembic.ini
├── docker-compose.yml              # desenvolvimento com PostgreSQL local
├── compose.production.yaml         # alternativa de produção com Compose
├── Dockerfile                      # imagem dos backends
└── README.md
```

## Persistência

### Produção atual

| Tipo | Local | Conteúdo |
|---|---|---|
| Banco | PostgreSQL gerenciado no Neon | Certificados, usuários, sessões, auditoria, rate limits e templates. |
| PDFs | Pasta privada no Google Drive | Arquivos definitivos dos certificados. |
| Segredos | Google Secret Manager | URL do banco, token do Drive, segredo JWT e segredo de HMAC. |
| Containers | Google Cloud Run | Aplicações efêmeras; não guardam dados permanentes. |

O banco guarda o `drive_file_id`, tamanho, tipo MIME e checksum SHA-256, mas não
guarda o PDF. A imagem de fundo do template é uma exceção intencional: ela fica
no banco como binário para que cada versão do template seja durável.

### Desenvolvimento

- Sem `DATABASE_URL`, a aplicação usa `database/certificates.db` em SQLite.
- Com `STORAGE_PROVIDER=local`, os PDFs ficam em `storage/pdfs/`.
- É possível usar PostgreSQL e Google Drive também no ambiente local.
- Arquivos `.db`, PDFs, planilhas, `.env` e a pasta `secrets/` estão ignorados
  pelo Git.

### Principais tabelas

| Tabela | Finalidade |
|---|---|
| `certificates` | Dados acadêmicos, estado e metadados dos arquivos. |
| `admin_users` | Usuários administrativos, papéis e hash de senha. |
| `auth_sessions` | Sessões JWT revogáveis no servidor. |
| `login_throttles` | Bloqueios persistentes por usuário/IP. |
| `public_rate_limits` | Limites compartilhados da área pública. |
| `audit_log` | Trilha de ações administrativas e incidentes. |
| `template_versions` | Layouts imutáveis e imagem de fundo do template. |

### Dados do certificado

Entre os principais campos estão nome, e-mail opcional, hash do documento,
curso, evento, carga horária, datas, texto, código único, status, versão do
template, usuário emissor, revogação e metadados do arquivo.

Os status permitidos são:

- `pending`: reservado no banco, mas ainda não finalizado;
- `ativo`: emitido e disponível;
- `revogado`: preservado para consulta, sem download;
- `failed`: emissão que não pôde ser concluída.

## Fluxos principais

### Emissão por planilha

1. A secretaria envia um arquivo `.xlsx`.
2. O backend valida o formato OOXML e os limites de tamanho/complexidade.
3. OpenPyXL e Pandas normalizam cabeçalhos, datas, cursos e carga horária.
4. A interface mostra um preview com linhas válidas e inválidas.
5. Após a confirmação, cada linha válida inicia uma emissão.
6. O banco reserva uma `business_key` e um código público em estado `pending`.
7. Pillow compõe o certificado com a versão ativa do template.
8. O QR Code recebe `PUBLIC_VALIDATION_BASE_URL/validar/{code}`.
9. O PDF é enviado ao storage configurado.
10. O banco recebe o ID do arquivo, checksum e tamanho e muda para `ativo`.
11. A ação e eventuais falhas são registradas na auditoria.

### Saga e idempotência

Não existe uma transação única que englobe PostgreSQL e Google Drive. Por isso:

- a reserva é confirmada no banco antes do upload;
- a finalização só ocorre após upload bem-sucedido;
- se a finalização falhar, o arquivo recém-enviado é excluído;
- estados interrompidos podem ser reparados por `reconcile.py`;
- a `business_key` possui restrição única e impede duplicação ao reenviar a
  mesma emissão.

### Contrato da planilha

| Coluna | Obrigatória | Observação |
|---|---|---|
| `nome` | Sim | Nome completo do participante. |
| `curso` | Sim | Validado contra a lista oficial. |
| `evento` | Sim | Campo distinto do curso. |
| `carga_horaria` | Sim | Número ou texto como `40h`. |
| `data_emissao` | Sim* | Pode vir da linha ou do valor padrão do formulário. |
| `email` | Não | Dado privado administrativo. |
| `documento` | Não | CPF, matrícula ou identificador para confirmação. |
| `data_inicio` | Não | Data inicial da atividade. |
| `data_fim` | Não | Data final da atividade. |

Cabeçalhos equivalentes, como `Carga Horária`, `CH` e `Data de Emissão`, são
reconhecidos. Datas podem chegar em `DD/MM/AAAA`, `AAAA-MM-DD` ou intervalos
suportados pelo normalizador. Internamente, datas persistidas usam ISO
`YYYY-MM-DD`.

### Template global

- Existe um único template global ativo por vez.
- Cada alteração cria uma nova versão, sem sobrescrever versões anteriores.
- A ativação de uma versão é explícita.
- O layout e a imagem de fundo são persistidos no PostgreSQL.
- Cada certificado guarda a versão e um snapshot do layout usado.
- Uma reemissão reproduz o certificado original mesmo que o template ativo
  tenha mudado.
- O editor permite texto, imagens, QR Code, fontes, dimensões e posicionamento.

### Consulta e download público

1. O aluno acessa a URL pública ou lê o QR Code.
2. A consulta busca o código no PostgreSQL.
3. Somente dados acadêmicos mínimos são apresentados.
4. Em um download, o backend recupera o arquivo pelo `drive_file_id`.
5. O conteúdo é validado como PDF e comparado com tamanho e SHA-256 registrados.
6. O backend transmite os bytes; o link e o ID do Drive não são expostos.

Na busca por nome, o código completo não é retornado. O backend fornece um
desafio opaco e exige confirmação posterior por documento/matrícula. Comparações
sensíveis usam HMAC e tempo constante.

## Segurança e privacidade

### Autenticação e autorização

- Senhas armazenadas com bcrypt.
- JWT assinado e entregue ao navegador somente em cookie `HttpOnly`.
- Cookie `Secure` obrigatório em produção e política `SameSite` configurável.
- Cada JWT possui uma sessão correspondente em `auth_sessions`.
- Logout, expiração e revogação global são validados no servidor.
- Papéis são consultados no banco em cada sessão relevante.
- Mutações autenticadas por cookie validam `Origin` ou `Referer` contra a
  allowlist administrativa.
- CORS de produção nunca aceita `*`.

### Proteções contra abuso

- Limite de tentativas de login por hash de usuário e IP.
- Atraso exponencial e bloqueio temporário.
- Rate limit público persistido, compartilhado entre instâncias.
- Confiança em `X-Forwarded-For` somente para proxies em
  `TRUSTED_PROXY_CIDRS`.
- Limites de página e tamanho mínimo da busca nominal.
- Limites de tamanho, linhas, colunas, células e tempo para planilhas.
- Validação de imagens e limites de pixels/elementos do template.

### Integridade

- Todo PDF possui checksum SHA-256 e tamanho registrados.
- Downloads verificam assinatura `%PDF-`, tamanho e checksum.
- Divergência marca o registro como `integrity_blocked`, gera auditoria e
  bloqueia a entrega.
- O storage local rejeita caminhos absolutos, `..` e acesso fora da pasta.
- Reemissão envia e confirma o novo arquivo antes de remover o anterior.

### LGPD e minimização

- Com `MINIMIZE_DOCUMENT_PLAINTEXT=true`, documento/matrícula não é persistido
  em claro; fica somente um HMAC normalizado.
- Logs e métricas não devem conter nome, e-mail ou documento.
- A API pública não retorna e-mail, documento, IDs internos ou caminhos.
- Certificados revogados permanecem consultáveis para rastreabilidade, mas não
  podem ser baixados.
- `PRIVATE_DATA_RETENTION_DAYS` permite expurgar e-mail e documento legado em
  claro após o prazo institucional definido.
- A instituição continua responsável por base legal, retenção, atendimento ao
  titular, backups e política de rotação dos segredos.

### Credenciais

Nunca versione:

- `.env` ou `.env.production`;
- JSON de cliente OAuth (`client_secret*.json`);
- token OAuth (`*oauth*token*.json` ou `token.json`);
- JSON/chaves de Service Account;
- conteúdo da pasta `secrets/`;
- planilhas ou PDFs reais.

O arquivo de cliente OAuth serve somente para a autorização inicial. Ele não é
o local onde certificados são armazenados. Em produção, o token resultante fica
no Google Secret Manager.

## Executar localmente

### Pré-requisitos

- Python 3.11 ou superior;
- Node.js 20 ou superior;
- npm;
- Git;
- PostgreSQL é opcional: sem ele, o desenvolvimento usa SQLite.

### 1. Configuração compartilhada

Na raiz do projeto:

```powershell
Copy-Item .env.example .env
```

Para o modo mais simples, mantenha:

```env
APP_ENV=development
DATABASE_URL=
STORAGE_PROVIDER=local
ADMIN_FRONTEND_URL=http://localhost:5173
PUBLIC_VALIDATION_BASE_URL=http://localhost:8001
```

O `.env` da raiz é lido pelos dois backends.

### 2. Backend administrativo

```powershell
cd certificados-admin\backEnd
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

API: `http://localhost:8000`

### 3. Usuário inicial

Defina no `.env` antes do primeiro start:

```env
ADMIN_INITIAL_USERNAME=secretaria
ADMIN_INITIAL_PASSWORD=troque-por-uma-senha-forte
ADMIN_INITIAL_ROLE=admin
```

Ou crie por linha de comando:

```powershell
cd certificados-admin\backEnd
python create_admin.py secretaria "uma-senha-forte"
```

Depois da criação, remova a senha em claro do `.env`.

### 4. Frontend administrativo

Em outro terminal:

```powershell
cd certificados-admin\frontend
npm ci
npm run dev
```

Painel: `http://localhost:5173`

Quando necessário, crie `certificados-admin/frontend/.env.local`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

### 5. Consulta pública

Em outro terminal:

```powershell
cd certificados-consulta
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Consulta: `http://localhost:8001`

### Portas locais

| Serviço | Porta |
|---|---:|
| API administrativa | 8000 |
| Frontend Vite | 5173 |
| Consulta pública | 8001 |

## Executar com Docker

O `docker-compose.yml` cria PostgreSQL local, aplica migrations, inicializa o
template e sobe as aplicações.

```powershell
Copy-Item .env.docker.example .env
docker compose build
docker compose up -d
docker compose logs -f admin
```

| Endpoint | Endereço |
|---|---|
| Consulta pública | `http://localhost` |
| Painel administrativo | `http://localhost:8080` |

Esse Compose usa HTTP e é destinado a desenvolvimento/integração. Não deve ser
exposto diretamente à internet.

Comandos úteis:

```powershell
docker compose ps
docker compose logs -f consulta
docker compose restart admin
docker compose down
```

## Configuração

A referência completa, com comentários e valores padrão, está em
`.env.example`. Variáveis de ambiente reais têm prioridade sobre o `.env`.

### Ambiente e URLs

| Variável | Finalidade |
|---|---|
| `APP_ENV` | `development` ou `production`. |
| `ADMIN_FRONTEND_URL` | Origem permitida do painel administrativo. |
| `CORS_ALLOWED_ORIGINS` | Allowlist administrativa alternativa. |
| `PUBLIC_VALIDATION_BASE_URL` | URL usada nos QR Codes. |
| `TRUSTED_PROXY_CIDRS` | Proxies autorizados a enviar IP encaminhado. |

### Banco

| Variável | Finalidade |
|---|---|
| `DATABASE_URL` | URL SQLAlchemy do PostgreSQL. |
| `DATABASE_URL_FILE` | Arquivo secreto contendo a URL. |
| `DB_PATH` | Caminho SQLite quando não há PostgreSQL. |
| `DB_POOL_SIZE` | Conexões permanentes do pool. |
| `DB_MAX_OVERFLOW` | Conexões extras permitidas. |
| `DB_POOL_TIMEOUT` | Tempo de espera por uma conexão. |
| `DB_POOL_RECYCLE` | Reciclagem de conexões em segundos. |

### Storage

| Variável | Finalidade |
|---|---|
| `STORAGE_PROVIDER` | `local` ou `google_drive`. |
| `LOCAL_STORAGE_PATH` | Raiz do storage local. |
| `GOOGLE_DRIVE_AUTH_MODE` | `oauth_user` ou `service_account`. |
| `GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID` | Pasta privada dos PDFs. |
| `GOOGLE_OAUTH_TOKEN_FILE` | Token OAuth em arquivo. |
| `GOOGLE_OAUTH_TOKEN_JSON_BASE64` | Token OAuth em base64. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | JSON de Service Account em arquivo. |
| `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` | JSON da Service Account em base64. |

### Autenticação, privacidade e limites

| Variável | Finalidade |
|---|---|
| `JWT_SECRET` / `JWT_SECRET_FILE` | Assinatura dos tokens administrativos. |
| `DOCUMENT_HASH_SECRET` / `_FILE` | HMAC de documentos e desafios públicos. |
| `JWT_EXPIRES_IN_MINUTES` | Duração da sessão. |
| `AUTH_COOKIE_SECURE` | Exige HTTPS para o cookie. |
| `AUTH_COOKIE_SAMESITE` | Política `lax`, `strict` ou `none`. |
| `LOGIN_MAX_FAILURES_PER_USER` | Limite de falhas por usuário. |
| `LOGIN_MAX_FAILURES_PER_IP` | Limite de falhas por IP. |
| `PUBLIC_RATE_LIMIT_REQUESTS` | Requisições públicas por janela. |
| `MINIMIZE_DOCUMENT_PLAINTEXT` | Evita persistir documento em claro. |
| `PRIVATE_DATA_RETENTION_DAYS` | Retenção de dados privados legados. |
| `MAX_SPREADSHEET_SIZE_MB` | Tamanho máximo da planilha. |
| `MAX_SPREADSHEET_ROWS` | Quantidade máxima de linhas. |

### Dados institucionais

| Variável | Finalidade |
|---|---|
| `ISSUE_LOCATION` | Local de emissão impresso. |
| `SIGNATORY_NAME` | Nome do signatário. |
| `SIGNATORY_TITLE` | Cargo/função do signatário. |

Em `APP_ENV=production`, PostgreSQL, Google Drive, URLs HTTPS, CORS e segredos
fortes são obrigatórios. O processo encerra no startup se a validação falhar.

## Google Drive

O sistema suporta dois modos.

### OAuth de usuário

É o modo usado no ambiente de produção atual.

1. No Google Cloud, ative a Google Drive API.
2. Configure a tela de consentimento OAuth.
3. Crie um cliente do tipo **Aplicativo para computador**.
4. Guarde o JSON fora do repositório.
5. Execute a autorização uma única vez:

```powershell
python -m pip install -r certificados-admin\backEnd\requirements.txt
python certificados-admin\backEnd\authorize_google_drive.py `
  --client-file "C:\segredos\client_secret.json" `
  --token-file "C:\segredos\certificados-oauth-token.json"
```

O utilitário usa o escopo limitado `drive.file`, cria ou reutiliza uma pasta
privada e informa o ID necessário. Configure:

```env
STORAGE_PROVIDER=google_drive
GOOGLE_DRIVE_AUTH_MODE=oauth_user
GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID=<id-da-pasta>
GOOGLE_OAUTH_TOKEN_FILE=C:\segredos\certificados-oauth-token.json
```

Ao repetir a autorização, use `--folder-id` para reutilizar a pasta. Em produção,
publique o aplicativo OAuth; tokens de aplicativos externos deixados em modo de
teste podem expirar rapidamente.

### Service Account

É indicada quando existe um Drive compartilhado do Google Workspace.

1. Crie uma Service Account e habilite a Google Drive API.
2. Compartilhe a pasta com o e-mail da conta de serviço.
3. Conceda somente a permissão necessária.
4. Configure o ID da pasta e o JSON por arquivo secreto ou base64.

```env
STORAGE_PROVIDER=google_drive
GOOGLE_DRIVE_AUTH_MODE=service_account
GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID=<id-da-pasta>
GOOGLE_SERVICE_ACCOUNT_FILE=C:\segredos\service-account.json
```

Os PDFs não são publicados. A leitura e o download sempre passam pelo backend.

## Banco e migrations

Os modelos em `database/models.py` são a fonte de verdade do schema. Produção
usa Alembic; SQLite de desenvolvimento também recebe inicialização compatível.

```powershell
# Aplicar todas as migrations
python -m alembic upgrade head

# Verificar a revisão atual
python -m alembic current

# Ver histórico
python -m alembic history

# Criar migration a partir dos modelos
python -m alembic revision --autogenerate -m "descricao"

# Verificar drift entre modelos e migrations
python -m alembic check
```

Migrations devem rodar uma vez por release antes da nova versão das APIs.

## API

FastAPI publica documentação OpenAPI em `/docs` e `/redoc` quando habilitada
pelo ambiente/aplicação.

### API administrativa

| Método e rota | Finalidade |
|---|---|
| `GET /health` | Estado do processo. |
| `GET /health/ready` | Prontidão do banco e dependências. |
| `GET /metrics` | Métricas administrativas. |
| `POST /auth/login` | Cria sessão e cookie. |
| `POST /auth/logout` | Revoga a sessão atual. |
| `GET /auth/me` | Usuário autenticado. |
| `POST /auth/sessions/revoke-all` | Revoga todas as sessões próprias. |
| `POST /auth/users/{id}/sessions/revoke-all` | Revogação por administrador. |
| `GET /courses` | Lista oficial de cursos. |
| `POST /certificates/validate-spreadsheet` | Preview da planilha. |
| `POST /certificates/generate` | Emissão das linhas válidas. |
| `GET /certificates` | Histórico paginado e filtrável. |
| `GET /certificates/{code}` | Detalhes administrativos. |
| `POST /certificates/{code}/revoke` | Revoga com motivo. |
| `POST /certificates/{code}/reissue` | Reemite com segurança. |
| `POST /certificates/download-zip` | Download em lote. |
| `GET /certificate-file/{code}` | PDF individual autenticado. |
| `GET /admin/certificates/{code}/metadata` | Metadados do arquivo. |
| `GET /templates/active` | Template global ativo. |
| `GET /templates/versions` | Histórico de templates. |
| `POST /templates/versions` | Cria uma versão imutável. |
| `POST /templates/versions/{id}/activate` | Ativa uma versão. |

### Consulta pública

| Método e rota | Finalidade |
|---|---|
| `GET /health` | Estado do processo. |
| `GET /health/ready` | Prontidão da aplicação. |
| `GET /` | Página inicial de consulta. |
| `GET /validar/{code}` | Página canônica do certificado. |
| `GET /public/verify/{code}` | Validação JSON por código. |
| `GET /public/search?nome=&page=` | Busca nominal paginada. |
| `GET /public/certificates/{code}/download` | Download por código. |
| `POST /public/certificates/download-by-name` | Download com confirmação. |
| `GET /certificado/{code}/download` | Compatibilidade com URL legada. |

## Testes e qualidade

### Backend

```powershell
cd certificados-admin\backEnd
python -m pytest tests -q
```

A suíte cobre autenticação, autorização, persistência, templates, geração,
planilhas, idempotência, saga, storage local/Drive fake, integridade, privacidade,
consulta pública e hardening.

Integração real com PostgreSQL exige um banco descartável:

```powershell
$env:TEST_DATABASE_URL="postgresql://usuario:senha@localhost:5432/certificados_test"
python -m pytest tests\test_integration_postgres.py -q
```

Sem `TEST_DATABASE_URL`, esses testes são ignorados e o restante usa SQLite.

### Frontend

```powershell
cd certificados-admin\frontend
npm run typecheck
npm test
npm run build
```

### Lint e migrations

```powershell
ruff check .
python -m compileall -q certificados-admin\backEnd certificados-consulta database storage_service observability
python -m alembic check
```

### Integração contínua

O workflow `.github/workflows/ci.yml` executa em pushes para `main` e pull
requests:

- Ruff e compilação do Python;
- aplicação das migrations e `alembic check`;
- testes Pytest;
- typecheck e build do frontend;
- auditorias `pip-audit` e `npm audit`;
- detecção de segredos com Gitleaks.

## Operação e observabilidade

### Logs

- Saída JSON estruturada.
- `correlation_id` por requisição.
- Propagação de `X-Request-ID`.
- Método, caminho, status e duração.
- Sem query string e sem dados pessoais.

### Métricas

`GET /metrics` na API administrativa apresenta contadores como:

- certificados gerados;
- duplicados;
- falhas;
- compensações executadas;
- downloads;
- incidentes de integridade.

As métricas atuais ficam em memória por instância; para visão consolidada em
múltiplas instâncias, devem ser exportadas/coletadas pela plataforma.

### Utilitários

Execute a partir de `certificados-admin/backEnd` com o ambiente configurado:

| Comando | Uso |
|---|---|
| `python create_admin.py <usuario> <senha>` | Cria usuário administrativo. |
| `python seed_template.py` | Cria/ativa o template inicial. |
| `python reconcile.py --dry-run` | Analisa estados internos interrompidos. |
| `python reconcile.py` | Repara estados conhecidos. |
| `python reconcile_drive.py` | Compara Drive e banco sem alterar arquivos. |
| `python reconcile_drive.py --apply` | Exclui do Drive os órfãos confirmados. |
| `python verify_integrity.py` | Valida PDFs, tamanhos e checksums. |
| `python migrate_to_drive.py --dry-run` | Simula migração local para Drive. |
| `python migrate_to_drive.py` | Migra PDFs locais. |
| `python migrate_dates.py --dry-run` | Analisa datas legadas. |
| `python migrate_dates.py` | Converte datas para ISO. |

Use sempre `--dry-run` quando disponível antes de uma operação corretiva.

### Backup e recuperação

O PostgreSQL é o mapa entre código público e arquivo no Drive. Perder o banco
torna os PDFs difíceis de localizar, mesmo que continuem no Drive. Portanto:

- mantenha backup periódico do PostgreSQL;
- preserve e teste a restauração dos segredos;
- não reutilize uma restauração antiga sem reconciliar banco e Drive;
- execute `reconcile_drive.py` após incidentes ou restaurações;
- valide checksums com `verify_integrity.py`;
- documente RPO, RTO e responsáveis institucionais.

Exemplo de backup lógico:

```bash
pg_dump "$DATABASE_URL" | gzip > certificados_$(date +%Y%m%d_%H%M%S).sql.gz
```

Consulte `docs/DEPLOY_E_RECUPERACAO.md` antes de restaurar produção.

## Deploy em produção

### Ambiente atual

Implantação registrada em **22/06/2026**:

| Recurso | Valor |
|---|---|
| Google Cloud Project | `certificados-prod-2ea4fc` |
| Região | `us-east1` |
| Banco | PostgreSQL no Neon |
| PDFs | Google Drive privado via OAuth |
| Consulta | [certificados-consulta](https://certificados-consulta-hj3rwyicha-ue.a.run.app) |
| API administrativa | [certificados-admin-api](https://certificados-admin-api-hj3rwyicha-ue.a.run.app) |
| Painel | [certificados-painel](https://certificados-painel-hj3rwyicha-ue.a.run.app) |
| Job de migrations | `certificados-migrate` |

Há duas imagens: uma para os backends e outra para o painel Nginx. O mesmo
container de backend seleciona `admin`, `consulta` ou `migrate` por
`APP_TARGET`.

### Release no Cloud Run

Pré-requisitos:

- Google Cloud CLI autenticado;
- projeto e APIs provisionados;
- Artifact Registry configurado;
- segredos criados no Secret Manager;
- service account de runtime com permissões mínimas;
- Git Bash no fluxo documentado para Windows.

Na raiz do repositório:

```bash
# Build das imagens, migrations e deploy dos três serviços
./deploy/cloudrun/deploy.sh release

# Consultar revisões e tráfego sem alterar recursos
./deploy/cloudrun/deploy.sh status
```

Etapas individuais:

```bash
./deploy/cloudrun/deploy.sh build
./deploy/cloudrun/deploy.sh build-web
./deploy/cloudrun/deploy.sh migrate
./deploy/cloudrun/deploy.sh consulta
./deploy/cloudrun/deploy.sh admin
./deploy/cloudrun/deploy.sh web
```

O script usa tags únicas, executa a migration como Cloud Run Job e só depois
implanta os serviços. Segredos são montados como arquivos em `/secrets`; eles não
entram na imagem nem são enviados como variáveis de texto no comando.

> Não altere `PUBLIC_VALIDATION_BASE_URL` sem manter compatibilidade com QR Codes
> já emitidos.

### Alternativa com Docker Compose

`compose.production.yaml` fornece uma opção para servidor próprio com Caddy,
HTTPS, containers somente leitura, secrets por arquivo, migrations explícitas e
backup por `pg_dump`. Consulte `docs/DEPLOY_PRODUCAO_DUAL.md` antes de usar essa
topologia.

## Documentação complementar

| Documento | Conteúdo |
|---|---|
| [docs/ARQUITETURA.md](docs/ARQUITETURA.md) | Componentes, persistência, saga e observabilidade. |
| [docs/CLOUD_RUN_ATUAL.md](docs/CLOUD_RUN_ATUAL.md) | Recursos e URLs da implantação atual. |
| [docs/DEPLOY_PRODUCAO.md](docs/DEPLOY_PRODUCAO.md) | Requisitos gerais de produção. |
| [docs/DEPLOY_PRODUCAO_DUAL.md](docs/DEPLOY_PRODUCAO_DUAL.md) | Topologia alternativa com Compose. |
| [docs/DEPLOY_E_RECUPERACAO.md](docs/DEPLOY_E_RECUPERACAO.md) | Backup, restore, rollback e recuperação. |
| [docs/DEPLOY_DOCKER.md](docs/DEPLOY_DOCKER.md) | Execução em containers. |
| [RELATORIO_AUDITORIA.md](RELATORIO_AUDITORIA.md) | Auditoria técnica e riscos analisados. |
| [RELATORIO_FINAL_IMPLEMENTACAO.md](RELATORIO_FINAL_IMPLEMENTACAO.md) | Histórico das melhorias implementadas. |

## Licença e responsabilidade

Não há arquivo de licença definido neste repositório. Antes de distribuir ou
publicar o código, a instituição deve escolher uma licença e revisar políticas
de privacidade, retenção, acesso ao Google Drive e tratamento de dados pessoais.
