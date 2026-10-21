# Fase funcional da secretaria

Data da validação: 13 de agosto de 2026.

Status: implementada e validada localmente. Nenhum deploy foi realizado.

## Matriz final de permissões

O contrato formal fica em `certificados-admin/backEnd/policies.py`. O backend
calcula as permissões efetivas em cada requisição e as publica em
`/auth/login` e `/auth/me`. O frontend usa essa lista para navegação e
affordances; ele não possui uma segunda matriz de papel para autorizar ações.

| Capacidade | `admin` | `secretaria` | `auditor` |
|---|---:|---:|---:|
| Painel operacional | Sim | Sim | Não |
| Consultar histórico e detalhe | Sim | Sim | Somente leitura |
| Emitir certificados e acompanhar lotes | Sim | Sim | Não |
| Download individual e em lote | Sim | Sim | Não |
| Revogar | Sim | Conforme configuração institucional | Não |
| Reemitir | Sim | Conforme configuração institucional | Não |
| Consultar e alterar templates | Sim | Não | Não |
| Gerir usuários e sessões de terceiros | Sim | Não | Não |
| Consultar trilha de auditoria | Sim | Não | Somente leitura |
| Consultar e alterar configurações | Sim | Não | Não |

Todo usuário autenticado pode trocar a própria senha, informando a senha
atual, e encerrar as próprias sessões. Um papel desconhecido recebe zero
permissões. As opções `secretaria_can_revoke` e
`secretaria_can_reissue` removem as permissões correspondentes em tempo de
execução, tanto da resposta de sessão quanto das ações da interface.

## Fluxos implementados

### Usuários, senhas e sessões

- Lista, criação, edição de nome/login/perfil, ativação e inativação.
- Redefinição administrativa com senha temporária forte, revogação das
  sessões existentes e troca obrigatória no próximo acesso. O administrador
  não pode usar esse endpoint sobre a própria conta.
- Troca da própria senha exige a senha atual, rejeita reutilização e revoga
  as demais sessões.
- Revogação de todas as sessões pelo administrador ou pelo próprio usuário.
- A sessão de primeiro acesso só abre a rota de troca de senha; endpoints de
  negócio recusam o acesso com um erro estruturado.
- Inativação da própria conta e remoção do último administrador ativo são
  bloqueadas transacionalmente.
- Mudanças de login, papel ou estado revogam as sessões afetadas.
- Não existe exclusão física de usuário: a inativação preserva referências
  de emissão e auditoria.
- Todas as projeções usam allowlist; hash e senha nunca fazem parte dos schemas
  de resposta ou do OpenAPI.

Endpoints principais:

- `GET/POST /admin/users`
- `PATCH /admin/users/{user_id}`
- `POST /admin/users/{user_id}/activate`
- `POST /admin/users/{user_id}/deactivate`
- `POST /admin/users/{user_id}/reset-password`
- `POST /admin/users/{user_id}/sessions/revoke-all`
- `POST /auth/change-password`
- `POST /auth/sessions/revoke-all`

### Auditoria consultável

- Página com paginação do servidor e filtros por categoria, ação, ator,
  alvo e período.
- Categorias formais para login bem-sucedido, falho e bloqueado; emissão;
  duplicidade; revogação; reemissão; downloads; templates; usuários;
  configurações e incidentes de integridade.
- Índices por ação/data, ator/data e alvo evitam varredura integral nas
  consultas usuais.
- Detalhes passam por allowlist e profundidade/tamanho limitados. Senhas,
  tokens, documentos, e-mail, corpo integral do certificado e conteúdo de
  arquivo não podem ser publicados pela API de auditoria.
- O motivo livre da revogação permanece apenas no registro de ciclo de vida do
  certificado; a auditoria registra que um motivo foi fornecido, sem duplicar
  texto que possa conter dado pessoal.

Endpoints: `GET /admin/audit` e `GET /admin/audit/categories`.

### Emissão em lote

- Download de planilha XLSX modelo com cabeçalhos, exemplo, larguras e painel
  congelado.
- Upload por drag and drop e por seletor de arquivo acessível.
- Pré-validação sem emissão, tabelas de linhas válidas/inválidas e exportação
  CSV de erros sem e-mail/documento.
- Visualização do texto interpolado antes da confirmação.
- Confirmação modal explícita e trava contra clique duplo.
- `Idempotency-Key` de 16 a 128 caracteres por lote, associado ao hash da
  planilha e dos parâmetros; reutilização conflitante retorna `409`.
- Registro persistente do lote e progresso real por linha, consultado por
  polling. A chave e o identificador ficam no `localStorage`, sem armazenar a
  planilha nem dados de participantes, para retomar a tela após atualização.
- Resumo final separa gerados, duplicados, inválidos e falhos e liga diretamente
  ao histórico filtrado pelo lote.
- Configurações institucionais são congeladas no snapshot do lote/certificado.
  Reemissões preservam instituição, local, assinante, cargo, URL e template
  originais.

Endpoints principais:

- `GET /certificates/spreadsheet-template`
- `POST /certificates/validate-spreadsheet`
- `POST /emission-batches`
- `GET /emission-batches/{batch_id}`
- `GET /emission-batches/by-idempotency-key/{idempotency_key}`
- `GET /emission-batches`

### Histórico e ciclo de vida

- Filtros persistentes na URL para nome, código, curso, evento, período,
  situação e lote.
- Paginação, ordenação e busca no servidor.
- Seleção da página para ZIP, com itens indisponíveis explicitamente
  ignorados e informados.
- Drawer de detalhe com situação de integridade, template, responsável pela
  emissão, lote, tamanho, datas, revogação e reemissões.
- Revogação exige motivo; reemissão exige confirmação e usa snapshots
  imutáveis.
- Downloads individuais e em lote verificam disponibilidade e integridade
  antes de servir o arquivo.
- Estados vazios, offline, sem permissão, rate limit e erro de servidor têm
  mensagens e ações de recuperação específicas.

### Configurações institucionais

- Singleton tipado para nome da instituição, local, assinante, cargo, URL
  pública, retenção, linhas por lote, tamanho de upload e regras de
  revogação/reemissão da secretaria.
- Nome institucional aplicado ao admin e à consulta pública.
- O editor visual oferece campos dinâmicos para instituição, local, linha de
  local/data, assinante e cargo; o valor vem do snapshot e não fica congelado
  como texto de negócio no layout.
- Limites de lote e upload são lidos do banco em cada validação.
- Segredos, credenciais, tokens e chaves continuam exclusivamente no ambiente
  seguro; nenhum campo de segredo existe na tabela de configurações.

Endpoints: `GET /institution`, `GET /admin/settings` e
`PUT /admin/settings`.

### Comportamento do frontend

- Menus, rotas e botões usam as permissões efetivas devolvidas pelo backend.
- Ações proibidas não são oferecidas; links diretos recebem uma explicação de
  acesso restrito.
- `401` encerra o estado local e informa sessão expirada; `403`, rate limit,
  offline e falha de servidor recebem tratamentos distintos. Uma conta
  inativada perde imediatamente suas sessões; no login, a mensagem permanece
  genericamente "usuário ou senha inválidos" para não permitir enumeração.
- Auditor sem painel é direcionado ao histórico, sua primeira área permitida.
- A troca obrigatória de senha intercepta todas as demais rotas autenticadas.

## Organização e arquivos da fase

O novo código de negócio não foi concentrado em `main.py`; o arquivo permanece
como raiz de composição, mantendo rotas legadas compatíveis e marcando a emissão
antiga como depreciada.

Backend e banco:

- `certificados-admin/backEnd/policies.py`
- `certificados-admin/backEnd/routers/{auth,audit,batches,certificates,settings,users}.py`
- `certificados-admin/backEnd/schemas/{auth,audit,batches,certificates,settings,users}.py`
- `certificados-admin/backEnd/services/{audit_service,batch_service,certificate_management,settings_service,user_service}.py`
- `certificados-admin/backEnd/{auth,main}.py`
- `certificados-admin/backEnd/services/{certificate_service,generator,template_service}.py`
- `database/{db,models,repositories}.py`
- `database/migrations/versions/0007_functional_workflows.py`

Frontend administrativo:

- `certificados-admin/frontend/src/app/` (sessão, instituição, guards,
  navegação e permissões)
- `certificados-admin/frontend/src/pages/{Usuarios,Auditoria,Configuracoes,EmitirCertificados,Historico,Perfil,AlterarSenha}.tsx`
- `certificados-admin/frontend/src/components/PasswordChangeForm.tsx`
- `certificados-admin/frontend/src/components/editor/{ElementList,PropertiesPanel}.tsx`
- `certificados-admin/frontend/src/{App,services/api,types/template}.ts*`
- Testes `*.test.ts(x)`, `playwright.config.ts` e `e2e/`.

Consulta pública:

- `certificados-consulta/app.py`
- `certificados-consulta/templates/{base,index,validar}.html`
- `certificados-consulta/render_states.py`

Testes e documentação:

- `certificados-admin/backEnd/tests/{conftest,test_functional_phase,test_templates}.py`
- Testes existentes de autenticação, geração, privacidade, storage e
  templates continuam na regressão completa.
- Este documento: `docs/FASE_FUNCIONAL_SECRETARIA.md`.

O worktree já continha as correções de segurança da fase anterior. Elas foram
preservadas; o inventário acima identifica os arquivos diretamente envolvidos
nesta fase funcional, e não atribui mudanças anteriores a esta entrega.

## Migration 0007

`0007_functional_workflows.py` é aditiva e revisa `0006`:

- complementa `admin_users` com nome, troca obrigatória, datas e criador;
- preenche `name = username` para contas existentes antes de tornar o campo
  obrigatório;
- cria o singleton `institutional_settings`, com limites e constraints;
- cria `emission_batches`, idempotência, contadores, progresso e resultados;
- liga certificados a lote e snapshot institucional;
- adiciona contagem, data e responsável de reemissão;
- adiciona índices de auditoria e lote;
- mantém colunas novas de certificado opcionais, preservando certificados
  legados.

Validações executadas:

- banco SQLite vazio: upgrade `0001 → 0007`;
- `alembic current`: `0007 (head)`;
- `alembic check`: sem operações pendentes;
- downgrade `0007 → 0006` e novo upgrade `0006 → 0007`;
- compilação offline PostgreSQL do intervalo `0006:0007`.

A criação/atualização local via ORM conserva ainda a migração aditiva de
SQLite legado, enquanto Alembic permanece a fonte de verdade em produção.

## OpenAPI

- Versão da API: `2.0.0`.
- Routers funcionais têm tags, schemas de request/response e `operation_id`.
- O schema é testado para conter os novos endpoints e para nunca conter
  `password_hash`.
- Documentação interativa continua desativada em produção, conforme as
  correções de segurança anteriores.

## Testes executados

| Comando/escopo | Resultado |
|---|---|
| `python -m compileall` no backend/banco/storage/observabilidade | Passou |
| `pytest -q` | 248 passaram, 4 pulados, 1 aviso de depreciação Starlette/httpx |
| `npm run typecheck` | Passou |
| `npm run build` | Passou |
| `npm test -- --reporter=dot` | 35 passaram em 10 arquivos |
| `npm run test:e2e` | 70 passaram, 28 condicionais pulados |
| Playwright da área pública com HTML renderizado | 24 passaram |
| Alembic SQLite: upgrade/check/downgrade/reupgrade | Passou |
| Alembic PostgreSQL offline `0006:0007` | Passou |

Os 28 skips da primeira execução Playwright são condicionais: 24 testes da
área pública precisam de `PUBLIC_HTML_DIR` e foram executados separadamente
com sucesso; os quatro restantes são variações de viewport/canvas que não se
aplicam ao projeto correspondente.

Os quatro skips do pytest são testes de integração PostgreSQL que exigem
`TEST_DATABASE_URL` e não encontraram uma instância de teste neste ambiente.

## Cobertura dos cenários críticos

| Cenário | Cobertura automatizada |
|---|---|
| Matriz exata, papel desconhecido e política dinâmica | Unitário/RBAC backend e frontend |
| Ciclo de usuário sem vazamento de hash/senha | Integração de API e componentes |
| Primeiro acesso e troca com senha atual | Integração de API e componentes |
| Auto-inativação, último admin e elevação indevida | Integração/RBAC |
| Sessão revogada, expirada e conta inativa | Regressão de autenticação e rotas frontend |
| Auditor somente leitura | Integração/RBAC e E2E desktop/mobile |
| Secretaria: planilha, conferência, confirmação e lote | Integração e E2E desktop/mobile |
| Admin: criação de usuário | Componentes e E2E desktop/mobile |
| Idempotência, conflito, progresso, resumo e filtro por lote | Integração de API e componentes |
| Lote integralmente inválido sem PII no relatório | Integração de API |
| Auditoria paginada/filtrável e minimizada | Integração de API, componente e E2E |
| Motivo de revogação sem duplicação na auditoria | Integração de API |
| Histórico, URL, seleção, revogação e ZIP | Componentes e E2E desktop/mobile |
| Variáveis institucionais no template visual | Unitário do gerador e typecheck frontend |
| Contrato OpenAPI sem material de senha | Integração de API |
| Acessibilidade das telas e estados públicos | Axe/Playwright desktop/mobile |
| Correções anteriores de privacidade, integridade e storage | Regressão backend completa |

Não foi gerado percentual de cobertura por linha: `pytest-cov` e o provider de
cobertura do Vitest não estão instalados no projeto. A cobertura informada acima
é de cenários e contratos observáveis.

## Limitações restantes

- O processamento de lote usa `BackgroundTasks` do processo FastAPI. Ele
  sobrevive a atualizações do navegador, mas não é uma fila externa durável: uma
  queda do processo pode deixar um lote em `processing`. Produção deve adotar
  worker/fila e reconciliação de lotes abandonados.
- A política de retenção é aplicada na preparação da aplicação. Não existe
  ainda um job periódico enquanto o processo permanece continuamente ativo.
- Os quatro testes PostgreSQL conectados não foram executados sem
  `TEST_DATABASE_URL`. A migration 0007 foi compilada para o dialeto e o ciclo
  completo foi exercitado em SQLite.
- A migration histórica 0005 executa leitura/conversão de dados e, por isso, a
  cadeia PostgreSQL desde zero não pode ser gerada inteiramente em modo offline;
  a 0007 isolada suporta a compilação offline.
- Os E2E dos três perfis utilizam o build de produção com uma API mock fiel ao contrato.
  A integração HTTP/DB real é coberta pelo pytest, mas ainda não há uma suíte de
  navegador contra PostgreSQL e storage reais.
- `/certificates/generate` foi mantido como endpoint legado depreciado para não
  quebrar integrações existentes. O fluxo novo usa `/emission-batches`.
- Nenhum deploy, alteração de ambiente remoto ou mutação de dados de produção
  foi realizada.
