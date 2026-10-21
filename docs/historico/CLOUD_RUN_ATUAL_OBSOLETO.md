# Ambiente Cloud Run

Identificadores e endpoints do ambiente real não fazem parte da entrega. Antes
de qualquer operação autorizada, defina explicitamente `PROJECT`, `REGION`,
`RUNTIME_SERVICE_ACCOUNT`, nomes dos serviços e hosts das APIs.

Os valores secretos devem ficar no Google Secret Manager. O container recebe apenas
caminhos para arquivos montados em `/secrets`; nenhum valor secreto faz parte da
imagem ou deste documento.

## Novo release

No Git Bash, a partir da raiz do repositorio:

```bash
./deploy/cloudrun/deploy.sh release
```

Para consultar o estado sem alterar recursos:

```bash
./deploy/cloudrun/deploy.sh status
```

O painel administrativo ja esta no Cloud Run. Se ele receber um dominio proprio,
defina `ADMIN_FRONTEND_URL` com a URL HTTPS final e execute somente o deploy do admin:

```bash
ADMIN_FRONTEND_URL=https://painel.exemplo.edu.br \
  ./deploy/cloudrun/deploy.sh admin
```

Nao altere `PUBLIC_VALIDATION_BASE_URL` depois de emitir certificados sem manter
compatibilidade com os QR Codes antigos.
