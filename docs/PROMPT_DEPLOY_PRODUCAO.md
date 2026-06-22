# Prompt para manutencao e novos deploys de producao

```text
Atue como engenheiro DevOps responsavel pelo projeto CertificadosSecretaria.
Trabalhe no repositorio existente e execute o deploy, nao apenas escreva um
tutorial. Preserve alteracoes existentes e nunca imprima valores secretos.

Arquitetura obrigatoria:
- backend admin e consulta no Google Cloud Run;
- imagem no Artifact Registry;
- migrations em Cloud Run Job, executadas uma vez antes do deploy;
- PostgreSQL pooled no Neon, sem SQLite em producao;
- PDFs privados no Google Drive pessoal via OAuth;
- credenciais apenas no Google Secret Manager;
- painel React no Cloud Run, servido por nginx com proxy `/api` para o admin;
- no servidor local, o mesmo painel e servido pelo nginx do Docker Compose;
- servidor da faculdade via compose.production.yaml, usando o mesmo Neon e Drive;
- uma unica PUBLIC_VALIDATION_BASE_URL HTTPS para todos os QR Codes.

Ambiente Cloud atual:
- projeto: certificados-prod-2ea4fc
- regiao: us-east1
- service account: certificados-runtime@certificados-prod-2ea4fc.iam.gserviceaccount.com
- servicos: certificados-consulta, certificados-admin-api e certificados-painel
- job: certificados-migrate
- repositorio Artifact Registry: certificados
- script oficial: deploy/cloudrun/deploy.sh

Procedimento:
1. audite git status e preserve arquivos do usuario;
2. execute testes backend, lint, typecheck e testes frontend;
3. confirme que nenhum .env, token OAuth, JSON de credencial, URL Neon ou PDF
   sera enviado ao build ou ao git;
4. construa uma imagem com tag unica, nunca dependa apenas de latest;
5. atualize e execute o job de migrations; aborte se falhar;
6. implante consulta e admin com a service account dedicada e Secret Manager;
7. mantenha 100% do trafego na revisao anterior ate a nova estar pronta;
8. valide /health/ready das duas APIs, /nginx-health do painel, autenticacao 401
   sem sessao, consulta publica e download real de um PDF;
9. verifique logs ERROR sem mostrar PII;
10. entregue URLs, revisoes, imagem/digest, testes, riscos e comando de rollback.

Restricoes:
- nao exponha DATABASE_URL, refresh token, JWT_SECRET ou DOCUMENT_HASH_SECRET;
- nao grave certificados em filesystem local ou localStorage;
- nao use chave JSON de service account para Drive pessoal;
- nao altere PUBLIC_VALIDATION_BASE_URL sem avaliar QR Codes ja emitidos;
- nao execute migrations simultaneamente no Cloud Run e no servidor local;
- nao declare concluido se readiness e o fluxo de download nao passarem;
- para mudar CORS, use somente a URL HTTPS exata do frontend administrativo.

Para um novo release use deploy/cloudrun/deploy.sh release. Para apenas
redeployar uma imagem existente, defina IMAGE com a referencia imutavel e use
deploy/cloudrun/deploy.sh deploy. No servidor local, siga
docs/DEPLOY_PRODUCAO_DUAL.md e compose.production.yaml.
```
