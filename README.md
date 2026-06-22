# Certificados Secretaria

Sistema de certificados acadêmicos dividido em **dois projetos independentes**
que compartilham o **mesmo banco de dados SQLite** e a **mesma pasta de PDFs**:

| Projeto | Para quem | O que faz |
|---|---|---|
| **`certificados-admin`** | Secretaria (uso interno) | Gera os certificados em PDF, grava cada um no banco e exibe o **código único** para anotar/enviar ao aluno. FastAPI + React. |
| **`certificados-consulta`** | Alunos (site público) | Busca por nome ou código; download direto por código e confirmação de documento após busca nominal. FastAPI + Jinja2. |

Os dois apontam para o mesmo `database/certificates.db` e `storage/pdfs/`, então
tudo que o admin gera aparece imediatamente na consulta.

## Estrutura de pastas

```text
CertificadosSecretaria/
├── database/
│   ├── schema.sql          # criação da tabela certificates
│   ├── db.py               # conexão + queries compartilhadas (importado pelos dois)
│   └── certificates.db     # SQLite (criado automaticamente no 1º uso)
├── storage/
│   └── pdfs/               # PDFs gerados ficam aqui
├── certificados-admin/     # Projeto 1 — secretaria (FastAPI + React)
│   ├── backEnd/            # API FastAPI + geração de PDF
│   └── frontend/           # interface React + Vite + Tailwind (inclui o editor visual)
├── certificados-consulta/  # Projeto 2 — site público (FastAPI + Jinja2)
│   ├── app.py
│   ├── templates/
│   ├── static/
│   └── requirements.txt
├── .env.example            # config compartilhada opcional (DATABASE_PATH, STORAGE_DIR)
└── README.md
```

## Pré-requisitos

- **Python 3.11+** (testado em 3.14) — para os dois backends
- **Node 18+** — apenas para o frontend do admin
- **PostgreSQL 13+** — em **produção** (dev/teste usam SQLite automaticamente)

## Persistência (banco e storage)

A arquitetura de persistência separa **metadados** (banco) de **arquivo
definitivo** (Google Drive):

- **Banco** — acesso via **SQLAlchemy** (camada de repositórios em
  `database/repositories.py`, sem SQL espalhado pelas rotas) com **pool de
  conexões** e **transações** (`database/engine.py`).
  - **Produção:** **PostgreSQL** por `DATABASE_URL` (obrigatório).
  - **Dev/teste:** **SQLite** local automático (quando `DATABASE_URL` está vazio).
- **Armazenamento dos PDFs** — em produção, **Google Drive é o único
  armazenamento definitivo**. O banco **nunca** guarda o PDF: apenas o
  `drive_file_id`, `checksum_sha256`, `file_size` e demais metadados. O storage
  local existe **só para desenvolvimento** (sem fallback em produção).
- **Código único** no formato **`CERT-ANO-XXXXXX`** (ex.: `CERT-2026-AB1234`).

O banco guarda **somente metadados**: código, participante, curso, evento,
datas, status, `business_key`, **template usado** (`template_used`),
`drive_file_id`, `checksum_sha256`, `file_size` e a trilha de auditoria. O
schema completo é a fonte única em `database/models.py`. (`pdf_path` permanece
como ponteiro **legado/dev** para compatibilidade com certificados antigos.)

### Migrations (Alembic)

O schema de produção é versionado com **Alembic** (`database/migrations/`):

```bash
# a partir da raiz do repo, com DATABASE_URL apontando para o PostgreSQL
alembic upgrade head            # aplica as migrations
alembic revision --autogenerate -m "mensagem"   # cria uma nova migration
alembic downgrade -1            # reverte a última
```

Em **desenvolvimento/teste** (SQLite) as tabelas são criadas automaticamente a
partir dos modelos ORM no primeiro start (e uma auto-migração leve adiciona
colunas novas a bancos SQLite antigos, sem perder dados).

### Configuração (opcional, via `.env`)

Sem nenhuma configuração já funciona com os caminhos padrão acima. Para apontar
para outros caminhos, copie `.env.example` para `.env` na **raiz** e ajuste —
os **dois projetos** leem o mesmo `.env`:

Veja todos os nomes e descrições em [.env.example](.env.example). Principais:

| Variável | Padrão | Descrição |
|---|---|---|
| `APP_ENV` | `development` | `development`/`production` (cookie Secure + fail-closed) |
| `DATABASE_URL` | — | **PostgreSQL em produção (obrigatório)**; vazio em dev → SQLite |
| `DB_PATH` | `database/certificates.db` | arquivo SQLite **só** quando `DATABASE_URL` vazio (dev) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `10` | pool de conexões (PostgreSQL) |
| `STORAGE_PROVIDER` | `local` (dev) / `google_drive` (prod) | em produção deve ser `google_drive` (sem fallback) |
| `LOCAL_STORAGE_PATH` | `storage/` | raiz dos PDFs locais (`<path>/pdfs`) |
| `GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID` | — | pasta do Drive onde os PDFs são salvos |
| `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` | — | credenciais da Service Account em base64 (produção) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | — | caminho do JSON da Service Account (dev local) |
| `PUBLIC_VALIDATION_BASE_URL` | `http://localhost:8001` (dev) | URL base da validação pública; explícita e HTTPS em produção |
| `ADMIN_FRONTEND_URL` | `http://localhost:5173` | origem administrativa permitida no CORS/CSRF; HTTPS obrigatório em produção |
| `CORS_ALLOWED_ORIGINS` | — | allowlist administrativa que substitui `ADMIN_FRONTEND_URL`; nunca aceita `*` |
| `JWT_SECRET` | (efêmero apenas em dev) | 32+ bytes aleatórios, com rejeição de baixa entropia; obrigatório em produção |
| `DOCUMENT_HASH_SECRET` | fallback somente em dev | HMAC de documentos/desafios; 32+ bytes aleatórios e obrigatório em produção |
| `TRUSTED_PROXY_CIDRS` | vazio | proxies autorizados a fornecer `X-Forwarded-For`; redes `/0` são rejeitadas |
| `PUBLIC_RATE_LIMIT_REQUESTS` / `PUBLIC_RATE_LIMIT_WINDOW_SECONDS` | `60` / `60` | limite público persistido no banco, compartilhado entre workers |
| `PUBLIC_NAME_SEARCH_MIN_LENGTH` / `PUBLIC_MAX_PAGE` | `3` / `100` | limites contra enumeração e paginação extrema |
| `MINIMIZE_DOCUMENT_PLAINTEXT` | `true` | persiste somente HMAC normalizado do documento |
| `PRIVATE_DATA_RETENTION_DAYS` | `0` | se >0, expurga e-mail/documento legado em claro após o prazo |
| `JWT_EXPIRES_IN_MINUTES` | `480` | validade do token de sessão |
| `AUTH_COOKIE_SECURE` / `AUTH_COOKIE_SAMESITE` | segue ambiente / `lax` | flags do cookie HttpOnly; Secure não pode ser desativado em produção |
| `AUTH_SESSION_RETENTION_DAYS` | `30` | retenção antes da limpeza de sessões expiradas |
| `LOGIN_MAX_FAILURES_PER_USER` / `LOGIN_MAX_FAILURES_PER_IP` | `8` / `20` | limites combinados persistidos no banco compartilhado |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` / `LOGIN_LOCKOUT_SECONDS` | `900` / `900` | janela e bloqueio temporário do login |
| `LOGIN_BACKOFF_BASE_MS` / `LOGIN_BACKOFF_MAX_MS` | `250` / `4000` | atraso exponencial assíncrono após falhas |
| `ADMIN_INITIAL_USERNAME` / `ADMIN_INITIAL_PASSWORD` / `ADMIN_INITIAL_ROLE` | — / — / `admin` | usuário inicial e papel (`admin`, `secretaria`, `auditor`) |
| `MAX_SPREADSHEET_SIZE_MB` / `MAX_SPREADSHEET_ROWS` | `10` / `2000` | limites da planilha |
| `ISSUE_LOCATION` / `SIGNATORY_NAME` / `SIGNATORY_TITLE` | — | local de emissão e assinante (impressos no PDF) |

> Nomes antigos (`DATABASE_PATH`, `STORAGE_DIR`, `FRONTEND_ADMIN_URL`,
> `JWT_TTL_MINUTES`, `ADMIN_USERNAME`/`ADMIN_PASSWORD`,
> `MAX_SPREADSHEET_FILE_SIZE_MB`) continuam aceitos como **alias**.
>
> ⚠️ Os dois projetos precisam usar **exatamente os mesmos valores** de
> `DB_PATH`/`LOCAL_STORAGE_PATH`, senão a consulta não encontra o que o admin gerou.

## Autenticação da secretaria (área administrativa)

A área administrativa exige **login**. As senhas são guardadas com **bcrypt** e
o JWT é entregue somente por cookie **Secure + HttpOnly + SameSite**; o token não
é devolvido no corpo. Cada `jti` possui uma linha em `auth_sessions`, portanto
logout, revogação global, expiração e desativação do usuário são efetivos no
servidor. `Authorization: Bearer` continua aceito para integrações, mas o login
web é cookie-only. As rotas públicas de consulta continuam abertas.

O login usa limites combinados por hash de IP e usuário, atraso exponencial e
bloqueio temporário. O estado fica em `login_throttles` no PostgreSQL
compartilhado, funcionando entre workers/deploys sem armazenamento em memória.
Sucessos, falhas e bloqueios são auditados sem senha. CAPTCHA não é a primeira
defesa.

**Criar o usuário inicial** (duas opções):

```powershell
# 1) Via variáveis de ambiente (criado automaticamente ao subir o backend)
#    no .env: ADMIN_INITIAL_USERNAME=secretaria ADMIN_INITIAL_PASSWORD=troque-esta-senha ADMIN_INITIAL_ROLE=admin

# 2) Via script seguro
cd certificados-admin\backEnd
python create_admin.py secretaria "uma-senha-forte"
```

**Em produção, defina obrigatoriamente:**

- `JWT_SECRET` gerado com pelo menos 32 bytes aleatórios; ausência, tamanho
  insuficiente ou baixa entropia aparente abortam o startup.
- `APP_ENV=production`, HTTPS e cookie Secure (não pode ser desativado).
- `ADMIN_FRONTEND_URL` HTTPS ou `CORS_ALLOWED_ORIGINS`; sem allowlist o startup
  aborta e `*` é rejeitado.

Operações mutáveis autenticadas por cookie validam explicitamente `Origin` ou
`Referer` contra a mesma allowlist. Requisições Bearer não dependem de cookie e
não passam por essa defesa CSRF.

Rotas de autenticação:

| Rota | Método | Função |
|---|---|---|
| `/auth/login` | POST | `{username, password}` → cria sessão e seta cookie HttpOnly; não retorna JWT |
| `/auth/logout` | POST | revoga a sessão no servidor e limpa o cookie |
| `/auth/me` | GET | dados do usuário autenticado |
| `/auth/sessions/revoke-all` | POST | revoga todas as sessões do próprio usuário |
| `/auth/users/{id}/sessions/revoke-all` | POST | revoga sessões de outro usuário; somente `admin` |

Rotas protegidas (exigem sessão): `/generate-certificates`, `/templates/*`,
`/certificate-file/{code}`, `/download-certificates`,
`/admin/certificates/{code}/metadata` e todo o grupo `/certificates*`. Toda
ação relevante (login, geração, revogação, reemissão, upload de template,
download em lote) é registrada na tabela `audit_log`.

Papéis são aplicados em runtime a partir do banco, não do JWT: `admin` gerencia
templates e sessões de qualquer usuário; `admin` e `secretaria` emitem/revogam;
`auditor` possui acesso somente às consultas administrativas. Usuários inativos
ou com papel desconhecido são recusados.

### Frontend administrativo, editor e histórico

O editor visual é carregado com `React.lazy` somente quando a aba correspondente
é aberta. O build mantém o Fabric.js em um chunk próprio e apresenta fallback e
limite de erro acessíveis durante o carregamento. Após essa separação, o JavaScript
inicial caiu de **588,11 kB (176,05 kB gzip)** para **267,30 kB (84,78 kB gzip)**;
o editor possui 31,03 kB e o Fabric.js 280,21 kB, ambos carregados sob demanda.

O histórico permite selecionar certificados individualmente ou por página,
limpar a seleção e baixar até 200 PDFs em ZIP. Revogados e registros sem arquivo
ficam desabilitados. O download exibe progresso quando o tamanho é conhecido e,
se parte dos arquivos ficar indisponível durante a operação, entrega os demais,
informa os códigos ignorados e inclui `_erros-download.txt` no ZIP.

Revogações usam modal com foco contido, fechamento por `Escape`, atributos ARIA
e restauração de foco. O motivo é obrigatório (5–500 caracteres) no frontend e
no backend. Respostas específicas do backend são preservadas, e qualquer `401`
durante a sessão encerra globalmente a interface autenticada e volta ao login.

Dependências verificadas em 19/06/2026: React 19.2.4, Vite 8.0.16,
Fabric.js 7.4.0, TypeScript 6.0.2 e Axios 1.18.0. A migração para Fabric 7 usa
seus tipos nativos; `@types/fabric` foi removido. `npm audit` terminou com
**0 vulnerabilidades**, portanto não há vulnerabilidade residual registrada e
nenhum `npm audit fix --force` foi executado.

## Template global (modelo único versionado)

Existe **um único template global** usado por **todos** os certificados — não há
templates por curso nem escolha de template por lote. O template é editado no
**editor visual** (aba “Template global”), e cada alteração cria uma **versão
imutável**; a secretaria **ativa explicitamente** a versão que deve valer.

- **Apenas uma versão ativa** por vez (ativação explícita).
- Cada versão guarda um **snapshot imutável** do layout (dimensões + elementos) e
  a **imagem de fundo em armazenamento durável** (BYTEA no PostgreSQL/SQLite —
  **nunca** em APPDATA nem em JSON local).
- Cada certificado registra `template_version_id` + `template_snapshot`, então a
  **reemissão reproduz fielmente** o certificado original (mesmo código, mesma
  versão), mesmo que a versão ativa já tenha mudado.
- **`event` e `course` são campos distintos** no layout (correção: antes o campo
  `event` recebia o curso). `ParticipantRegistryRecord` carrega ambos.

Rotas (admin, exceto o background da imagem que é público e não-sensível):

| Rota | Método | Função |
|---|---|---|
| `/templates/active` | GET | versão ativa (com layout) |
| `/templates/versions` | GET | histórico de versões |
| `/templates/versions/{id}` | GET | uma versão (com layout) |
| `/templates/versions/{id}/background` | GET | imagem de fundo (stream) |
| `/templates/versions` | POST | cria uma nova versão imutável |
| `/templates/versions/{id}/activate` | POST | ativa a versão (apenas uma ativa) |

No primeiro start (ou via `python seed_template.py`) uma **versão padrão** é
criada e ativada a partir de `templates/certificado_base.png`. A migração de
schema (`template_versions`, `template_version_id`, `template_snapshot`) é a
Alembic `0002`; os stores antigos (template por curso em APPDATA e
`visual_templates.json`) foram **removidos**.

**Reemissão segura no Drive.** Ao reemitir, o **novo** arquivo é enviado e
**finalizado no banco antes** de o arquivo antigo ser excluído; se a atualização
do banco falhar, o novo arquivo é removido e o **arquivo anterior é preservado**
(sem órfãos e sem perda).

## Emissão por planilha (modelo estruturado)

A secretaria emite certificados a partir de uma planilha `.xlsx`. As colunas são
reconhecidas por sinônimos e normalizadas internamente:

| Coluna | Obrigatória | Observação |
|---|---|---|
| `nome` | ✅ | nome completo |
| `curso` | ✅ | validado contra a lista oficial (`/courses`) |
| `evento` | ✅ | **distinto do curso** |
| `carga_horaria` | ✅ | numérica (ex.: `40`, `40h`) |
| `data_emissao` | ✅* | por linha; `*` pode usar um padrão do formulário |
| `email`, `documento`, `data_inicio`, `data_fim` | — | opcionais |

Os cabeçalhos aceitam variações (ex.: "Carga Horária", "CH" → `carga_horaria`;
"Data de Emissão" → `data_emissao`). Datas aceitam `dd/mm/aaaa`, `aaaa-mm-dd` ou
intervalo `20 a 25/10/2025`.

**Exemplo de planilha** (`.xlsx`, primeira linha = cabeçalho):

| nome | email | documento | curso | evento | carga_horaria | data_inicio | data_fim | data_emissao |
|---|---|---|---|---|---|---|---|---|
| Ana Carolina Souza | ana@ex.com | 12345 | Direito | Semana Jurídica | 40 | 20/10/2025 | 25/10/2025 | 10/06/2026 |
| Bruno Lima | | | Pedagogia | Congresso de Educação | 8 | | | 10/06/2026 |

> Linhas inválidas (curso fora da lista, carga não numérica, data inválida) **não**
> geram certificado — aparecem no preview com o motivo do erro.

Fluxo (todas as rotas exigem sessão admin):

1. `POST /certificates/validate-spreadsheet` → **preview** com linhas válidas,
   inválidas (com motivos) e contagens. **Nada é gerado ou gravado.**
2. `POST /certificates/generate` → gera **apenas** as linhas válidas, cria
   código único + **QR Code**, salva no storage e no banco. Retorna um resumo
   (`generated`, `duplicates`, `failed`, `invalid`).

**Geração transacional (saga + compensação).** Como uma transação ACID não
abrange PostgreSQL + Google Drive, cada certificado segue uma *saga* por etapas,
e o resumo da API reflete **exatamente** o que foi persistido:

1. **Reserva** (transação no banco): calcula a `business_key`, gera o código e
   **insere** uma linha `pending` — a unicidade de código e `business_key` é
   garantida pelas **constraints UNIQUE** (sem `INSERT OR IGNORE` nem checagem
   fora da transação). Colisão de código → novo código; colisão de
   `business_key` → o certificado existente volta em `duplicates`.
2. **Upload**: renderiza o PDF em memória e envia ao storage (Drive em produção;
   nunca grava cópia local definitiva).
3. **Finalização** (transação no banco): grava `drive_file_id`, `checksum`,
   `file_size` e marca `ativo`.
4. **Falha**: nunca retorna sucesso — marca `failed`, **exclui o arquivo do
   Drive** se o upload ocorreu mas a finalização falhou, e registra na auditoria.

**Reconciliação.** Para reparar estados deixados por uma queda no meio da saga
(`pending` antigos, `ativo` sem arquivo, `failed` com arquivo órfão):

```powershell
cd certificados-admin\backEnd
python reconcile.py --dry-run     # apenas relatório
python reconcile.py               # executa (idempotente; pode ir no cron)
```

**Idempotência:** a `business_key`
(`sha256(nome+documento+evento+curso+carga+data)`) tem índice **UNIQUE**.
Reenviar a mesma planilha **não** duplica — as linhas repetidas voltam em
`duplicates` com o código já existente.

**Histórico admin:** `GET /certificates` (filtros: `name`, `code`, `course`,
`event`, `status`; `limit`/`offset`), `GET /certificates/{code}`,
`POST /certificates/{code}/revoke`, `POST /certificates/{code}/reissue`,
`POST /certificates/download-zip`.

**QR Code:** aponta sempre para
`PUBLIC_VALIDATION_BASE_URL/validar/{code}`. A URL é construída por uma única
função compartilhada, que normaliza barras e rejeita URLs relativas, credenciais,
query strings e fragmentos. Em produção, `PUBLIC_VALIDATION_BASE_URL` é
obrigatória e deve usar HTTPS. O código textual continua impresso no certificado.

## Área pública (consulta)

HTML e JSON usam **rate limit persistente no banco compartilhado** e projeções
sanitizadas. O IP de `X-Forwarded-For` só é aceito quando o peer pertence a
`TRUSTED_PROXY_CIDRS`:

| Rota | Método | Função |
|---|---|---|
| `/validar/{code}` | GET | página HTML canônica; mostra válido, revogado ou inexistente |
| `/public/verify/{code}` | GET | valida por código; sinaliza **revogado** |
| `/public/search?nome=&page=` | GET | busca nominal paginada; sem código completo ou link direto |
| `/public/certificates/{code}/download` | GET | download pelo código (sem expor o Drive) |
| `/public/certificates/download-by-name` | POST | confirma documento/matrícula e baixa após busca nominal |

A página HTML canônica `/validar/{code}` expõe apenas nome, curso/evento, carga
horária, data, código e status. E-mail, documento, IDs internos, caminhos e
metadados do Drive nunca entram no contexto do template. O download é oferecido
somente para certificados ativos; revogados não exibem o botão e retornam `410`
na rota de download. Respostas recebem CSP, proteção contra framing/MIME sniffing,
política de referência/permissões e tratamento de erro acessível.

A pesquisa por código é exata e libera download apenas quando o certificado está
ativo. A busca por nome remove acentos e usa lowercase, exige termo mínimo,
escapa `%`, `_` e `\\`, limita páginas e retorna somente dados acadêmicos mínimos
mais um desafio HMAC opaco. Ela nunca revela `unique_code` completo nem URL de
download. O POST de download compara o HMAC do documento em tempo constante; código,
documento ou desafio incorretos recebem a mesma resposta. A rota legada apenas
redireciona para a rota canônica e passa pelo mesmo rate limit.

No PostgreSQL, `participant_name_normalized` possui índice trigram GIN para a
busca parcial e índice composto por status. O rate limit fica em
`public_rate_limits`, não na memória do processo, portanto funciona com múltiplos
workers/deploys que compartilham o banco.

## Armazenamento de certificados (Local / Google Drive)

Os PDFs passam por uma **camada de armazenamento plugável** (`storage_service/`),
selecionada por `STORAGE_PROVIDER`. Nenhuma rota, o `main.py` ou o `generator.py`
falam com o Google Drive diretamente — tudo passa pela interface
`CertificateStorage`.

```
storage_service/
├── base.py          # interface CertificateStorage + StoredFile/RetrievedFile
├── local.py         # LocalStorage  (desenvolvimento)
├── google_drive.py  # GoogleDriveStorage (produção, Service Account)
├── config.py        # leitura de variáveis de ambiente (sem segredos no código)
└── __init__.py      # get_storage() + download_certificate() (com fallback local)
```

Ao gerar um certificado, o PDF é renderizado em memória, enviado para o storage
configurado e os **metadados** são gravados no banco: `storage_provider`,
`drive_file_id`, `drive_folder_id`, `original_filename`, `mime_type`,
`file_size`, `checksum_sha256`, `created_at`. O **código verificador**
(`CERT-ANO-XXXXXX`) continua sendo o identificador público.

### Desenvolvimento (LocalStorage)

Padrão. Não precisa de nada:

```env
STORAGE_PROVIDER=local
```

Os PDFs ficam em `storage/pdfs/` e o download é servido pelo backend.

### Produção (GoogleDriveStorage)

**1) Criar a Service Account**

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/) e crie (ou
   selecione) um projeto.
2. Ative a **Google Drive API** (APIs & Services → Library → *Google Drive API*).
3. Em **IAM & Admin → Service Accounts**, crie uma Service Account.
4. Na aba **Keys** da Service Account, **Add Key → Create new key → JSON** e baixe
   o arquivo. **Não comite esse JSON** (já está no `.gitignore`).

**2) Compartilhar a pasta do Drive com a Service Account**

1. No Google Drive, crie a pasta que vai guardar os certificados.
2. Copie o **e-mail** da Service Account (algo como
   `nome@projeto.iam.gserviceaccount.com`).
3. Clique com o botão direito na pasta → **Compartilhar** → adicione esse e-mail
   como **Editor**.
4. Pegue o **ID da pasta** na URL: `https://drive.google.com/drive/folders/<ESTE_ID>`.

**3) Configurar as variáveis de ambiente**

```env
STORAGE_PROVIDER=google_drive
GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID=<id-da-pasta>

# Opção recomendada em produção: JSON inteiro em base64
GOOGLE_SERVICE_ACCOUNT_JSON_BASE64=<base64-do-json>
# Alternativa para dev local: caminho do arquivo JSON
# GOOGLE_SERVICE_ACCOUNT_FILE=C:\caminho\para\service-account.json
```

Gerar o base64 do JSON:

```powershell
# PowerShell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("service-account.json"))
```
```bash
# Linux/macOS
base64 -w0 service-account.json
```

Instale as dependências do Google (já listadas no `requirements.txt`):

```powershell
pip install -r requirements.txt
```

### Segurança do armazenamento

- Os PDFs **não** são tornados públicos no Drive — só a Service Account (e quem
  você compartilhar a pasta) tem acesso.
- A área pública **nunca** recebe link do Drive nem IDs internos: o download
  passa pelo backend usando o **código verificador**.
- Antes de servir, o backend valida que o certificado **existe** e está
  **ativo** (certificados com `status = 'revogado'` retornam `410`).
- Credenciais vêm **apenas** de variáveis de ambiente — nunca do banco nem do
  código.

### Compatibilidade com certificados antigos

A migração do schema é automática (`init_db()` adiciona as novas colunas sem
perder dados). Certificados antigos, salvos em `storage/pdfs/`, continuam
funcionando: se um registro **não** tiver `drive_file_id`, o backend faz
**fallback** e serve o arquivo local.

### Rotas relevantes

| Rota | Acesso | Função |
|---|---|---|
| `GET /certificate-file/{code}` | Admin (sessão) | Visualiza/baixa o PDF via storage |
| `GET /admin/certificates/{code}/metadata` | Admin (sessão) | Metadados de armazenamento |
| `GET /certificado/{code}/download` (consulta) | Público | Download pelo código, sem expor o Drive |

## Robustez e integridade (datas, arquivos, banco, uploads)

- **Datas (ISO, ordenação cronológica).** `issue_date`, `start_date` e
  `end_date` são armazenadas em **ISO `YYYY-MM-DD`** (com índice em
  `issue_date`), então a ordenação é **cronológica** — o formato "por extenso"
  é aplicado **apenas na apresentação** (API/HTML/PDF). Para converter bases
  antigas: `python migrate_dates.py --dry-run` (relatório das não conversíveis)
  e depois `python migrate_dates.py`.
- **Integridade dos arquivos.** Todo download verifica que o conteúdo é um
  **PDF** e que **tamanho + SHA‑256** batem com o registrado. Em divergência o
  certificado é **bloqueado** (`integrity_blocked`), registra-se um
  **incidente** na auditoria e o conteúdo **não é entregue**. Verificação
  periódica: `python verify_integrity.py` (agende no cron).
- **Constraints de banco.** `CHECK` em `status`, `role` e `storage_provider`;
  **FKs** de `issued_by`, `revoked_by` e `audit_log.actor_id` para
  `admin_users` com **`ON DELETE SET NULL`** — remover/desativar um usuário
  **não destrói** certificados nem auditoria (o vínculo é apenas anulado).
- **Uploads.** A planilha é validada como **OOXML real** com limites de linhas,
  colunas, tamanho de célula e tempo aplicados **antes** de carregar tudo
  (guarda contra **bombas de descompressão**). Imagens de template usam
  `Image.verify()` + limites de **pixels/dimensões**; o layout limita
  **quantidade de elementos** e o **tamanho total de data URLs**.
- **Caminhos locais.** O storage de desenvolvimento **rejeita** caminhos
  **absolutos** e **`..`**, confinando a leitura/escrita ao diretório de storage.

## Operação, observabilidade e documentação

- **Logs estruturados (JSON)** com `correlation_id` (cabeçalho `X-Request-ID`) e
  **métricas** em `GET /metrics` (admin): geração, duplicados, falhas,
  compensações, downloads e incidentes de integridade. **Sem dados pessoais** em
  logs/métricas (`observability/`).
- **Ferramentas de operação** (CLIs em `certificados-admin/backEnd/`):
  | Comando | Função |
  |---|---|
  | `python migrate_to_drive.py --dry-run` | Migra PDFs locais → Drive (idempotente, checksum, relatório) |
  | `python verify_integrity.py` | Verificação periódica de integridade dos arquivos |
  | `python reconcile.py` | Reconcilia estado interno (pending/órfãos) |
  | `python reconcile_drive.py` | Reconcilia Drive × banco (apenas ids/códigos, sem PII) |
  | `python migrate_dates.py` | Converte datas legadas → ISO (relatório) |
  | `python seed_template.py` | Cria/ativa o template global padrão |
- **CI** em `.github/workflows/ci.yml`: lint (ruff), typecheck/build do frontend,
  testes, migrations + `alembic check`, auditoria de dependências (pip-audit/npm
  audit) e detecção de segredos (gitleaks).
- **Documentação detalhada**: [docs/ARQUITETURA.md](docs/ARQUITETURA.md) e
  [docs/DEPLOY_E_RECUPERACAO.md](docs/DEPLOY_E_RECUPERACAO.md) (deploy, backup/
  restore do PostgreSQL, Shared Drive e permissões mínimas, rollback).

> O fluxo legado `POST /generate-certificates` foi **removido**; toda emissão usa
> o fluxo estruturado `POST /certificates/generate` (saga + template global).

## Como rodar

> Comandos de ativação do venv para **Windows PowerShell**. No `cmd` use
> `.venv\Scripts\activate.bat`; no Linux/macOS, `source .venv/bin/activate`.

### 1) certificados-admin (secretaria)

**Backend** (porta 8000):

```powershell
cd certificados-admin\backEnd
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

**Frontend** (porta 5173):

```powershell
cd certificados-admin\frontend
npm install
npm run dev
```

A interface abre em `http://localhost:5173` e fala com o backend em
`http://localhost:8000`. Ao gerar certificados, cada item mostra o **código**
(com botão *Copiar*) para a secretaria enviar ao aluno.

### 2) certificados-consulta (site público)

Porta 8001 (para rodar junto com o admin):

```powershell
cd certificados-consulta
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Acesse `http://localhost:8001`, busque por nome ou código e clique em
**Baixar PDF**.

## Fluxo completo

1. A secretaria envia a planilha + dados no **admin** → o sistema gera o PDF,
   grava no banco (`CERT-ANO-XXXXXX`) e mostra o código.
2. O aluno acessa a **consulta**, busca pelo nome ou pelo código e baixa o PDF.

## Portas usadas

| Serviço | Porta |
|---|---|
| Admin — backend (FastAPI) | 8000 |
| Admin — frontend (Vite) | 5173 |
| Consulta — site público | 8001 |

Para mudar a porta de um backend Python, defina `PORT` no ambiente antes de
iniciar (ex.: `$env:PORT=9000; python app.py`).

## Como rodar os testes

```powershell
cd certificados-admin\backEnd
python -m pytest tests -q
```

A suíte cobre: normalização de datas, camada de storage (Local + Drive fake),
planilha/validação, geração + idempotência + QR, autenticação e rotas
protegidas, histórico/revogação, a área pública, a **camada de persistência
SQLAlchemy** (repositórios, transações, normalização de `DATABASE_URL`) e os
**checks de fail-closed** de produção.

Os testes de **integração com PostgreSQL** (`tests/test_integration_postgres.py`)
rodam apenas quando há um banco de teste descartável disponível:

```powershell
$env:TEST_DATABASE_URL="postgresql://user:pass@localhost:5432/certificados_test"
python -m pytest tests/test_integration_postgres.py -q
```

Sem `TEST_DATABASE_URL` eles são **ignorados** (skip), e o restante da suíte roda
sobre SQLite.

## Migração de PDFs antigos para o Google Drive

Para mover certificados que ainda estão em `storage/pdfs/` (sem `drive_file_id`)
para o Drive, use o script (já configurando o Drive no `.env`):

```powershell
cd certificados-admin\backEnd
python migrate_to_drive.py --dry-run     # simula e mostra o relatório, sem enviar
python migrate_to_drive.py               # executa de fato
python migrate_to_drive.py --limit 100   # processa no máximo 100
```

O script verifica a existência do arquivo, faz upload pela camada de storage,
grava `drive_file_id` + metadados + `checksum_sha256` (mantendo o `pdf_path`
local como backup), **não** reenvia certificados que já têm `drive_file_id`, e
imprime um relatório final (migrados / ignorados / não encontrados / falhas).

> Os PDFs antigos em `certificados-admin/backEnd/output/certificados/` são
> artefatos de versões anteriores (antes do storage compartilhado), **não**
> referenciados pelo banco — podem ser removidos manualmente após conferência.

## Deploy seguro (resumo)

Admin e consulta podem rodar em **deploys separados**, compartilhando o **mesmo
PostgreSQL** (`DATABASE_URL`) e os **mesmos arquivos privados no Drive**:

- **PostgreSQL gerenciado** comum aos dois deploys; rode `alembic upgrade head`
  no deploy (uma vez) antes de subir. **Backup diário** do PostgreSQL (é o mapa
  código ↔ `drive_file_id`).
- **Drive privado**: os PDFs **nunca** são públicos. A **consulta** não recebe
  credenciais administrativas nem URLs públicas — o download é **sempre
  proxiado pelo backend** pelo `drive_file_id`. Recomenda-se provisionar uma
  **Service Account somente-leitura** para a consulta (a mesma pasta
  compartilhada como *Leitor*), enquanto o admin usa uma SA com escrita.
- Exponha à internet **apenas a consulta**; mantenha o **admin** na rede
  interna/VPN. **HTTPS** obrigatório; `APP_ENV=production`.
- Em `APP_ENV=production` a aplicação **falha ao iniciar** se faltar
  `DATABASE_URL`, `JWT_SECRET` forte, `DOCUMENT_HASH_SECRET` forte, allowlist CORS administrativa,
  `PUBLIC_VALIDATION_BASE_URL` HTTPS, a pasta do Drive ou as credenciais — e
  `STORAGE_PROVIDER` precisa ser `google_drive` (sem fallback local).
- **CORS** restrito a `ADMIN_FRONTEND_URL`/`CORS_ALLOWED_ORIGINS` (nunca `*`);
  mutações por cookie também validam `Origin`/`Referer`.
- **Segredos só no `.env`/secret manager**: `JWT_SECRET` forte; **nunca** comite
  o JSON da Service Account (já bloqueado no `.gitignore`).
- Use uvicorn atrás de nginx; com PostgreSQL o pool suporta múltiplos workers.

## Retenção e privacidade (LGPD)

- O documento/matrícula é normalizado e transformado em HMAC-SHA-256 com
  `DOCUMENT_HASH_SECRET`; com `MINIMIZE_DOCUMENT_PLAINTEXT=true`, o valor em
  claro nunca é persistido. Logs e respostas nunca recebem o documento.
- O HMAC pseudonimizado é mantido enquanto a instituição oferecer download por
  busca nominal. Ele não é reversível sem o segredo, mas continua sendo dado
  pessoal pseudonimizado e deve permanecer sob os mesmos controles de acesso.
- `PRIVATE_DATA_RETENTION_DAYS>0` apaga e-mail e eventual documento legado em
  claro no startup após o prazo. `0` exige política/rotina institucional externa;
  essa escolha evita apagar automaticamente registros sem base normativa local.
- A busca nominal revela somente nome e dados acadêmicos mínimos; o código
  completo e o link direto não são retornados. A confirmação posterior usa o
  documento/matrícula sem revelar se ele existe.
- Certificados revogados permanecem consultáveis como revogados para
  rastreabilidade, mas não podem ser baixados.
- A área administrativa (com todos os dados) exige **login** e registra ações
  na tabela `audit_log` (quem emitiu/revogou e quando).
- A instituição deve definir base legal, prazo para metadados acadêmicos/PDF,
  retenção do `audit_log`, atendimento ao titular e rotação/backup do segredo.
  Rotacionar `DOCUMENT_HASH_SECRET` exige recalcular hashes a partir de uma fonte
  autorizada; sem o documento original, confirmações antigas deixam de funcionar.
- Solicitações de titulares (LGPD) devem ser tratadas pela secretaria; a
  exclusão de um certificado deve ser feita de forma controlada (preferir
  revogação à exclusão física, para manter a trilha de auditoria).
