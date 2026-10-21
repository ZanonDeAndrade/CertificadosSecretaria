# Servidor local na LAN

O perfil operacional é `compose.local-server.yaml`. Ele publica somente Nginx
na porta 80 e mantém PostgreSQL, FastAPI e worker na rede Docker interna.

```text
Cliente LAN -> http://192.168.2.192:80 -> Nginx
                                           |- SPA React e /api -> FastAPI admin
                                           |- /consulta e /consulta-api -> FastAPI público
                                           `- PostgreSQL + worker + runtime/storage
```

Use `docs/DEPLOY_LOCAL_SERVER.md` para instalação, firewall, backup, restore,
reboot e teste em outro computador. O perfil exige segredos gerados por
`scripts/bootstrap_local_server_secrets.sh`, PostgreSQL persistente e storage
local em `runtime/storage`; não requer DNS, domínio, HTTPS público, Redis ou
Google Drive.

URLs finais:

```text
http://192.168.2.192
http://192.168.2.192/consulta/
```
