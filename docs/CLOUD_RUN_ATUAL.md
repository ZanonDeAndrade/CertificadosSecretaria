# Ambiente Cloud Run atual

Data da implantacao: 2026-06-22.

| Recurso | Valor |
|---|---|
| Projeto | `certificados-prod-2ea4fc` |
| Regiao | `us-east1` |
| Repositorio | `certificados` |
| Service account | `certificados-runtime@certificados-prod-2ea4fc.iam.gserviceaccount.com` |
| Consulta | `https://certificados-consulta-hj3rwyicha-ue.a.run.app` |
| Admin API | `https://certificados-admin-api-hj3rwyicha-ue.a.run.app` |
| Painel da secretaria | `https://certificados-painel-hj3rwyicha-ue.a.run.app` |
| Job de migrations | `certificados-migrate` |

Os valores secretos ficam no Google Secret Manager. O container recebe apenas
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
