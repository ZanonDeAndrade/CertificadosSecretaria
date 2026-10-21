# Manual de instalação

Não execute estes passos em produção sem revisar a checklist separada do
relatório de prontidão. Este manual instala; ele não faz deploy.

## Versões e recursos

- Linux x86-64 testado localmente;
- Python 3.12.13 e `uv` 0.12.3;
- Node.js 20.20.2 e npm 10.8.2;
- PostgreSQL 16 para integração/produção;
- Docker 29/Compose 5 para a alternativa containerizada.

As versões canônicas estão em `.python-version`, `.node-version`, `uv.lock` e
`package-lock.json`.

## Instalação local descartável

```bash
uv sync --frozen --group dev
cp .env.example .env
uv run alembic upgrade head
uv run certificados-admin
```

Em outro terminal:

```bash
uv run certificados-consulta
```

E, para o painel:

```bash
cd certificados-admin/frontend
npm ci --no-audit --no-fund
npm run dev
```

No modo de desenvolvimento sem `DATABASE_URL`, o código aceita SQLite e storage
local. Não coloque dados reais nesse modo.

## PostgreSQL de integração

Crie banco e usuário descartáveis. Exemplo conceitual (substitua apenas por
valores de teste, nunca publique a senha):

```bash
export DATABASE_URL='postgresql+psycopg://cert_test:SENHA_DE_TESTE@127.0.0.1:5432/certificados_test?sslmode=disable'
export TEST_DATABASE_URL="$DATABASE_URL"
export APP_ENV=test
export CERTIFICADOS_DISABLE_DOTENV=1
uv run alembic upgrade head
uv run alembic check
```

O banco de teste deve poder ser apagado. Produção exige PostgreSQL, URL via
secret file e TLS verificado segundo `database/config.py`.

## Configuração obrigatória de produção

Use `.env.production.example` somente como inventário. Valores secretos devem
ser montados por arquivo/Secret Manager. No mínimo:

- `APP_ENV=production`;
- `DATABASE_URL_SECRET_FILE` com PostgreSQL e `sslmode=verify-full`;
- `JWT_SECRET_FILE` forte e distinto;
- keyring HMAC de documentos e id ativo;
- keyring AES-GCM de payloads de lote e id ativo;
- `PUBLIC_VALIDATION_BASE_URL` HTTPS;
- origem administrativa/CORS exatas;
- `STORAGE_PROVIDER=google_drive`; a pasta global é apenas compatibilidade legada;
- cliente OAuth web/Picker, API key restrita somente à Google Picker API,
  callback HTTPS e client secret montado por Secret Manager. Não aplique
  restrição HTTP referrer: a chave é validada no iframe oficial
  `docs.google.com`, e não na origem do painel. O nome canônico consumido pelo processo é
  `GOOGLE_PICKER_CLIENT_SECRET_FILE`; `GOOGLE_PICKER_CLIENT_SECRET_NAME` identifica
  apenas o recurso no Secret Manager usado pelo script de Cloud Run;
- identidades técnicas distintas de upload e leitura pública, correspondentes
  às credenciais de backend;
- credencial administrativa Drive `read_write` e pública `read_only`, separadas;
- chave/destino de backup independentes.

As aplicações falham fechadas em produção quando os controles exigidos estão
ausentes. Não reutilize chave JWT como HMAC, job ou backup.

Em desenvolvimento direto, o arquivo apontado por
`GOOGLE_PICKER_CLIENT_SECRET_FILE` deve conter somente o Client Secret e ter
permissão `0600`. A API Key restrita ao Picker segue a mesma regra por meio de
`GOOGLE_PICKER_API_KEY_FILE`. No Compose, informe os caminhos desses arquivos no
host; eles são montados em `/run/secrets`. O Client ID e a API Key não entram no
bundle do React: o backend fornece ao Picker apenas uma sessão curta autenticada
e marcada como `no-store`.

## Migrations e bootstrap

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run python -m certificados_backend.create_admin
```

Senhas novas têm no mínimo 6 caracteres e precisam conter letra maiúscula,
letra minúscula, número e caractere especial. A senha não pode conter o nome
de usuário, ser comum, incluir caracteres de controle nem ultrapassar o limite
de 72 bytes do bcrypt.

O comando de criação administrativa deve ser executado em canal protegido. A
migration atual é `0009`. Faça backup e restore drill antes de migrar ambiente
existente; downgrade é ferramenta de compatibilidade, não plano de rollback de
dados por si só.

Em PostgreSQL, somente Alembic administra o schema, inclusive em desenvolvimento.
As migrations `0007`, `0008` e `0009` reconhecem tabelas futuras compatíveis que tenham
sido pré-criadas por uma versão antiga do startup. Não use `alembic stamp`, não
apague tabelas e não altere `alembic_version` manualmente para contornar erro de
migration.

## Worker e manutenção

```bash
uv run certificados-worker --max-jobs 1000 --poll-seconds 2
uv run certificados-maintenance cleanup-operational-state
uv run certificados-integrity
```

O worker precisa das chaves de payload, PostgreSQL e Drive de escrita. A consulta
pública não deve receber credencial de escrita.

## Containers locais

```bash
cp .env.docker.example .env
docker compose build
docker compose up -d db migrate admin consulta worker web
docker compose ps
```

O `docker-compose.yml` publica HTTP para desenvolvimento e não deve ser exposto
à internet. `compose.production.yaml` é referência de topologia e ainda requer
segredos, domínio, TLS, backups e operação institucional.

## Verificação pós-instalação

- readiness da API e consulta responde;
- migration atual é `0009` e `alembic check` não aponta drift;
- login sintético funciona e papel proibido recebe `403`;
- lote sintético produz PDF/QR e não duplica no retry;
- validação pública encontra o código sintético;
- revogado e PDF adulterado não baixam;
- backup criado é restaurado em banco descartável.
