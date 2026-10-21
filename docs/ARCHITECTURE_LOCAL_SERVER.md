# Arquitetura do servidor local

O perfil `compose.local-server.yaml` é o perfil operacional para uma única
máquina Linux na LAN. Ele não usa Redis, fila externa, Caddy, Cloud Run nem
serviço de hospedagem público.

```text
Navegador na LAN
        |
        | HTTP :80
        v
Nginx (container web)
  | /              -> React/Vite compilado (SPA)
  | /api/*         -> FastAPI administrativo
  | /consulta/*    -> FastAPI de consulta pública
  | /validar/*     -> FastAPI de validação por QR Code
  | /consulta-api/ -> API pública usada pelo painel
        |
        v
PostgreSQL + diretório persistente runtime/storage
        ^
Worker durável (fila armazenada no PostgreSQL; healthcheck de conexão)
```

Somente `web` publica a porta HTTP. O banco, as APIs e o worker não possuem
portas mapeadas para o host e ficam na rede Docker `172.29.0.0/24`.

## Persistência

- `postgres_data` é o volume Docker que guarda o banco PostgreSQL.
- `runtime/storage` no host guarda PDFs emitidos. O diretório é montado em
  `/data/storage` nos containers que precisam dele.
- `secrets/local-server` contém senha do banco, URLs e chaves. Não pertence ao
  Git e deve receber backup protegido separado.
- `backups/` é somente um destino local padrão; não protege contra falha do
  disco do próprio servidor.

## Capacidade inicial

O Compose limita a API administrativa a 512 MB, consulta a 384 MB, worker a
512 MB, PostgreSQL a 512 MB e Nginx a 128 MB. Cada serviço HTTP inicia com um
único processo. PostgreSQL inicia com `shared_buffers=128MB` e no máximo 40
conexões; os pools das APIs usam 2 conexões e 1 overflow.

Em servidor de 2 GB, mantenha `ADMIN_WORKERS=1` e `CONSULTA_WORKERS=1`. O
worker é necessário porque a emissão usa fila durável; não adicione Redis ou
outro worker. Acompanhe `docker stats` durante emissões grandes.

Na validação em repouso, os containers consumiram aproximadamente 114 MiB
(admin), 67 MiB (consulta), 36 MiB (PostgreSQL), 4 MiB (Nginx) e 109 MiB
(worker), cerca de 330 MiB no total dos containers. Isso não inclui Docker,
kernel, cache, nem picos de emissão. Os limites configurados somam cerca de
2,0 GiB; por isso 2 GB é viável somente para carga pequena e monitorada, e
**4 GB é a capacidade recomendada** para operação regular.

As imagens da aplicação compartilham camadas, mas o cache de build pode crescer
nas atualizações. A manutenção e retenção de backups estão em
`docs/DEPLOY_LOCAL_SERVER.md`.

## Caminho público

- Painel: `/`.
- Consulta de certificados: `/consulta/`.
- QR Code: `/validar/CODIGO`.
- API administrativa: `/api/health` e `/api/health/ready`.

`LOCAL_SERVER_URL` centraliza a origem usada por cookies, CORS e QR Codes. Ao
migrar para outro IP, altere esse único valor em `.env.local-server`, execute
`./deploy.sh` e reemita somente certificados que precisem apontar para a nova
URL. Para domínio com HTTPS futuro, troque a origem, ative TLS no proxy e
defina `AUTH_COOKIE_SECURE=true`; o código de frontend continua usando `/api`.
