# Ambientes de execução

O projeto usa a mesma base de código em dois perfis operacionais. A escolha é
feita por arquivo de ambiente e Compose, nunca por IP fixo no código.

| Perfil | Arquivo | Banco e storage | URLs públicas |
| --- | --- | --- | --- |
| Desenvolvimento nativo | `.env` copiado de `.env.example` | SQLite por padrão; PostgreSQL local opcional; filesystem local | Vite `http://localhost:5173`, API `:8000`, consulta `:8001` |
| Desenvolvimento Docker | `.env.docker` copiado de `.env.docker.example` | PostgreSQL e volume Docker `storage_data` | consulta `http://localhost`, admin `http://localhost:8080` |
| Servidor LAN | `.env.local-server` copiado de `.env.local-server.example` | PostgreSQL, `runtime/storage` e secrets locais persistentes | `http://192.168.2.192` e `/consulta/` |

Não execute os dois Composes ao mesmo tempo: ambos publicam a porta 80.

## Desenvolvimento nativo

```bash
uv sync --frozen --group dev
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn certificados_backend.main:app --host 127.0.0.1 --port 8000
uv run uvicorn certificados_consulta.app:app --host 127.0.0.1 --port 8001
```

Em outro terminal:

```bash
cd certificados-admin/frontend
npm ci --no-audit --no-fund
npm run dev
```

Sem `DATABASE_URL`, o desenvolvimento usa SQLite em `database/certificates.db`.
Para testar PostgreSQL local, defina somente `DATABASE_URL` no `.env`; nunca
adicione essa senha a arquivos versionados. O frontend usa as URLs de
desenvolvimento apenas no build/dev server; builds de produção usam `/api` e
`/consulta-api` relativos.

## Desenvolvimento Docker

```bash
cp .env.docker.example .env.docker
DEVELOPMENT_ENV_FILE=.env.docker docker compose --env-file .env.docker up -d --build
DEVELOPMENT_ENV_FILE=.env.docker docker compose --env-file .env.docker ps
curl --fail http://127.0.0.1:8080/api/health/ready
```

O perfil cria o volume `storage_data`, inicializado com UID/GID `10001` e modo
`750`; admin e worker escrevem nele e a consulta o monta somente para leitura.
Ele usa worker externo com fila durável no PostgreSQL. Para parar sem apagar
dados: `DEVELOPMENT_ENV_FILE=.env.docker docker compose down`. Não use
`down -v` quando quiser preservar banco e PDFs.

## CORS e cookies

No modo nativo, Vite (`localhost:5173`) acessa FastAPI diretamente; a allowlist
de desenvolvimento contém apenas origens localhost conhecidas. No Compose de
desenvolvimento e no servidor LAN, a SPA chama caminhos relativos pelo Nginx,
evitando CORS entre navegador e API. A API ainda valida `Origin` em métodos de
escrita e nunca usa `Access-Control-Allow-Origin: *`.

Cookies são `HttpOnly` e `SameSite=Lax`. No perfil LAN, `AUTH_COOKIE_SECURE=false`
é necessário porque a origem é HTTP; em produção HTTPS, use `true`.

## URLs e migração futura

`LOCAL_SERVER_URL` centraliza IP/domínio LAN, CORS e QR Code. Para adotar
HTTPS futuro, altere essa variável, configure TLS no proxy e ative
`AUTH_COOKIE_SECURE=true`; o frontend continua chamando `/api`.
