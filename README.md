# Certificados Secretaria

Sistema de certificados acadêmicos dividido em **dois projetos independentes**
que compartilham o **mesmo banco de dados SQLite** e a **mesma pasta de PDFs**:

| Projeto | Para quem | O que faz |
|---|---|---|
| **`certificados-admin`** | Secretaria (uso interno) | Gera os certificados em PDF, grava cada um no banco e exibe o **código único** para anotar/enviar ao aluno. FastAPI + React. |
| **`certificados-consulta`** | Alunos (site público) | Busca certificados **por nome** (parcial) ou **por código** e permite **baixar o PDF**. Sem login. FastAPI + Jinja2. |

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

## Banco e storage compartilhados

- Banco **SQLite** em `database/certificates.db`, criado automaticamente na
  primeira execução de qualquer um dos projetos.
- PDFs salvos em `storage/pdfs/` e referenciados pelo banco (coluna `pdf_path`).
- Código único no formato **`CERT-ANO-XXXXXX`** (ex.: `CERT-2026-AB1234`),
  gerado automaticamente ao salvar.

Tabela `certificates`:

| Campo | Descrição |
|---|---|
| `id` | chave primária |
| `unique_code` | código único (ex.: `CERT-2026-AB1234`) |
| `participant_name` | nome completo do aluno |
| `event_name` | nome do curso/evento |
| `issue_date` | data de emissão |
| `pdf_path` | caminho do PDF (relativo a `storage/`) |
| `certificate_text` | texto completo do certificado |
| `created_at` | data de criação do registro |

### Configuração (opcional, via `.env`)

Sem nenhuma configuração já funciona com os caminhos padrão acima. Para apontar
para outros caminhos, copie `.env.example` para `.env` na **raiz** e ajuste —
os **dois projetos** leem o mesmo `.env`:

Veja todos os nomes e descrições em [.env.example](.env.example). Principais:

| Variável | Padrão | Descrição |
|---|---|---|
| `APP_ENV` | `development` | `development`/`production` (afeta o cookie Secure) |
| `DB_PATH` | `database/certificates.db` | arquivo SQLite compartilhado |
| `STORAGE_PROVIDER` | `local` | `local` (dev) ou `google_drive` (produção) |
| `LOCAL_STORAGE_PATH` | `storage/` | raiz dos PDFs locais (`<path>/pdfs`) |
| `GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID` | — | pasta do Drive onde os PDFs são salvos |
| `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` | — | credenciais da Service Account em base64 (produção) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | — | caminho do JSON da Service Account (dev local) |
| `PUBLIC_VALIDATION_BASE_URL` | — | URL base da validação pública (para o QR) |
| `ADMIN_FRONTEND_URL` / `PUBLIC_APP_URL` | (dev) | origens permitidas no CORS |
| `CORS_ALLOWED_ORIGINS` | — | lista (vírgula) que sobrepõe as duas acima |
| `JWT_SECRET` | (efêmero) | segredo do JWT da secretaria (**obrigatório em produção**) |
| `JWT_EXPIRES_IN_MINUTES` | `480` | validade do token de sessão |
| `AUTH_COOKIE_SECURE` | (segue `APP_ENV`) | cookie de sessão Secure (HTTPS) |
| `ADMIN_INITIAL_USERNAME` / `ADMIN_INITIAL_PASSWORD` | — | usuário admin inicial (seed no 1º start) |
| `MAX_SPREADSHEET_SIZE_MB` / `MAX_SPREADSHEET_ROWS` | `10` / `2000` | limites da planilha |
| `ISSUE_LOCATION` / `SIGNATORY_NAME` / `SIGNATORY_TITLE` | — | local de emissão e assinante (impressos no PDF) |

> Nomes antigos (`DATABASE_PATH`, `STORAGE_DIR`, `FRONTEND_ADMIN_URL`,
> `JWT_TTL_MINUTES`, `ADMIN_USERNAME`/`ADMIN_PASSWORD`,
> `MAX_SPREADSHEET_FILE_SIZE_MB`) continuam aceitos como **alias**.
>
> ⚠️ Os dois projetos precisam usar **exatamente os mesmos valores** de
> `DB_PATH`/`LOCAL_STORAGE_PATH`, senão a consulta não encontra o que o admin gerou.

## Autenticação da secretaria (área administrativa)

A área administrativa agora exige **login**. As senhas são guardadas com **bcrypt**
e a sessão usa um **JWT** entregue por **cookie HttpOnly** (o backend também aceita
`Authorization: Bearer` para clientes de API/testes). As rotas públicas de
validação/consulta **continuam abertas**.

**Criar o usuário inicial** (duas opções):

```powershell
# 1) Via variáveis de ambiente (criado automaticamente ao subir o backend)
#    no .env:  ADMIN_INITIAL_USERNAME=secretaria   ADMIN_INITIAL_PASSWORD=troque-esta-senha

# 2) Via script seguro
cd certificados-admin\backEnd
python create_admin.py secretaria "uma-senha-forte"
```

**Em produção, defina obrigatoriamente:**

- `JWT_SECRET` (32+ bytes aleatórios) — sem ele os tokens não sobrevivem a reinícios.
- `APP_ENV=production` (ou `AUTH_COOKIE_SECURE=true`, atrás de HTTPS).
- `ADMIN_FRONTEND_URL` e `PUBLIC_APP_URL` — o CORS **nunca** usa `*`.

Rotas de autenticação:

| Rota | Método | Função |
|---|---|---|
| `/auth/login` | POST | `{username, password}` → seta cookie + retorna token |
| `/auth/logout` | POST | limpa o cookie de sessão |
| `/auth/me` | GET | dados do usuário autenticado |

Rotas protegidas (exigem sessão): `/generate-certificates`, `/upload-template`,
`/visual-templates*`, `/certificate-file/{code}`, `/download-certificates`,
`/admin/certificates/{code}/metadata` e todo o grupo `/certificates*`. Toda
ação relevante (login, geração, revogação, reemissão, upload de template,
download em lote) é registrada na tabela `audit_log`.

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
   (`generated`, `duplicates`, `invalid`).

**Idempotência:** cada certificado tem uma `business_key`
(`sha256(nome+documento+evento+curso+carga+data)`) com índice **UNIQUE**.
Reenviar a mesma planilha **não** duplica — as linhas repetidas voltam em
`duplicates` com o código já existente.

**Histórico admin:** `GET /certificates` (filtros: `name`, `code`, `course`,
`event`, `status`; `limit`/`offset`), `GET /certificates/{code}`,
`POST /certificates/{code}/revoke`, `POST /certificates/{code}/reissue`,
`POST /certificates/download-zip`.

**QR Code:** aponta para `PUBLIC_VALIDATION_BASE_URL/validar/{code}`. Defina
`PUBLIC_VALIDATION_BASE_URL` para a URL pública; o código textual continua
impresso no certificado.

## Área pública (consulta)

JSON, com **rate limit** básico e projeção **sanitizada** (sem e-mail, documento
ou ids internos):

| Rota | Método | Função |
|---|---|---|
| `/public/verify/{code}` | GET | valida por código; sinaliza **revogado** |
| `/public/search?nome=&page=` | GET | busca por nome, **paginada** |
| `/public/certificates/{code}/download` | GET | download pelo código (sem expor o Drive) |

A página HTML (`/`) também pagina a busca por nome e mostra certificados
revogados com selo, sem botão de download.

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
protegidas, histórico/revogação e a área pública.

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

- **1 servidor** (os dois backends compartilham o SQLite). Exponha à internet
  **apenas a consulta**; mantenha o **admin** na rede interna/VPN.
- **HTTPS** obrigatório; `APP_ENV=production` (cookie de sessão Secure).
- **CORS** restrito a `ADMIN_FRONTEND_URL`/`PUBLIC_APP_URL` (nunca `*`).
- **Segredos só no `.env`**: `JWT_SECRET` forte; **nunca** comite o JSON da
  Service Account (já bloqueado no `.gitignore`).
- **PDFs no Drive** não são públicos; o download passa sempre pelo backend.
- **Backup diário** do arquivo SQLite (é o mapa código ↔ arquivo no Drive).
- Use uvicorn atrás de nginx; poucos workers (SQLite WAL: vários leitores + 1
  escritor).

## Retenção e privacidade (LGPD)

- O certificado contém dados pessoais (nome; opcionalmente e-mail/documento).
  **e-mail e documento nunca** são expostos na área pública — a consulta
  devolve apenas nome, curso/evento, carga horária, data, código e status.
- O download público exige o **código verificador**; certificados **revogados**
  não podem ser baixados e aparecem como revogados na validação.
- A área administrativa (com todos os dados) exige **login** e registra ações
  na tabela `audit_log` (quem emitiu/revogou e quando).
- **Retenção:** defina por quanto tempo os certificados e o `audit_log` ficam
  armazenados conforme a política da instituição; a revogação preserva o
  registro (status `revogado`) para rastreabilidade, sem apagar o histórico.
- Solicitações de titulares (LGPD) devem ser tratadas pela secretaria; a
  exclusão de um certificado deve ser feita de forma controlada (preferir
  revogação à exclusão física, para manter a trilha de auditoria).
