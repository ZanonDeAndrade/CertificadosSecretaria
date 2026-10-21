# Revisão técnica atual — CertificadosSecretaria

**Data da revisão:** 13/08/2026
**Fonte canônica:** `HEAD` `12ef877113fcc8b55aa8f2f4142367a9bdb7fd41`
**Escopo:** código e artefatos locais; nenhuma correção, commit, deploy ou acesso a ambiente real
**Referências de compatibilidade:** Python 3.12 e Node.js 20

## Nota de escopo e método

Esta revisão confronta o `README.md`, `RELATORIO_AUDITORIA.md`,
`RELATORIO_FINAL_IMPLEMENTACAO.md`, todos os documentos canônicos de `docs/` e o
texto extraído de `Relatorio_Tecnico_Certificados.pdf` com o código do `HEAD`. Os
relatórios anteriores são tratados como registros históricos, não como prova de
implementação.

O código foi analisado a partir de uma exportação limpa do `HEAD`. As diferenças
preexistentes do diretório de trabalho foram inventariadas e preservadas. Não foi
aberto o conteúdo de `.env`, credenciais, bancos, planilhas ou PDFs com dados de
participantes; para esses artefatos foram usados somente nome, caminho, tipo,
tamanho e metadados de empacotamento. Apenas o PDF técnico indicado no escopo teve
texto extraído. Nenhuma credencial foi validada ou utilizada.

As validações de código foram executadas em cópias descartáveis. Dependências e
imagens obtidas durante a etapa inicial da revisão, ainda sob a solicitação
anterior de instalação limpa, ficaram fora do repositório. Após a delimitação final
do escopo, não houve nova consulta externa. Resultados que dependem de estado de
produção ou de serviços externos não compõem o parecer.

Classificações funcionais usadas neste documento:

- **Implementado e comprovado:** código presente e comportamento coberto por teste executado ou inspeção determinística suficiente.
- **Parcialmente implementado:** existe fluxo útil, mas há lacuna funcional, defensiva ou operacional relevante.
- **Apenas documentado:** há instrução ou promessa, sem implementação operacional comprovada.
- **Ausente:** não foi localizada implementação.
- **Não foi possível validar:** a verificação exigiria sistema externo, dado real ou teste não disponível no escopo.

## 1. Resumo executivo

O projeto possui uma arquitetura funcional de três aplicações, persistência
compartilhada, emissão por planilha, PDF/QR, histórico, revogação, templates,
consulta pública e controles defensivos relevantes. A suíte backend chegou a
**197 testes aprovados e 3 ignorados** depois da inclusão, somente no ambiente
descartável, de uma dependência de teste ausente. O frontend passou em instalação
limpa, typecheck, 12 testes e build com Node 20. SQLite e PostgreSQL efêmero aceitaram
upgrade/downgrade das migrations.

Isso não torna a entrega atual apta a publicação. Há seis bloqueios P0:

1. o pacote local contém `.env`, arquivos de credencial, bancos auxiliares,
   planilhas, PDFs, logs, caches, `node_modules` e uma cópia de `.git` contaminada;
2. a busca pública nominal devolve o próprio valor que autoriza o download, sem a
   confirmação independente prometida no README;
3. nomes são consultados por `GET` e podem permanecer em URL, histórico, cache e
   logs de proxy;
4. a aplicação pública recebe a mesma credencial OAuth do Drive usada pelo admin,
   com escopo capaz de criar e excluir arquivos do aplicativo;
5. Uvicorn aceita cabeçalhos encaminhados de qualquer origem, enfraquecendo os
   limites por IP;
6. o repositório local falha na verificação integral do Git por milhares de
   duplicatas com sufixo `(2)` dentro de `.git`.

Também foram comprovadas falhas de retentativa após emissão `failed`, condições de
corrida em criação/ativação de templates, divergência de migrations no PostgreSQL,
validação de planilha incompatível com o contrato documentado, geração/ZIP
síncronos em memória, RBAC apenas no backend e lacunas de CI, acessibilidade,
backup/restore e operação multi-worker.

### Veredito objetivo

| Destino | Veredito | Condição objetiva |
|---|---|---|
| Desenvolvimento local | **Apto com restrições** | Usar somente dados sintéticos, SQLite descartável e storage local; reconhecer que a instalação backend declarada não coleta os testes sem dependência adicional. |
| Demonstração acadêmica | **Não apto no estado da entrega** | Torna-se apto após P0 de higiene, bloqueio/correção da busca nominal, preparação reproduzível e roteiro exclusivamente sintético/offline. |
| Homologação | **Não apto** | Faltam correções P0/P1, testes E2E, acessibilidade, concorrência, restauração e integração de staging. |
| Produção | **Não apto** | Há riscos confirmados de privacidade, privilégio excessivo, rate limiting, consistência, rollout, recuperação e observabilidade. |

## 2. Avaliação geral do projeto

A base técnica é melhor do que os primeiros relatórios históricos descrevem: a
autenticação não é apenas um JWT sem estado, a saga possui reserva/finalização e
compensação, os PDFs têm metadados de integridade, e o storage está abstraído. O
problema atual não é ausência completa de engenharia; é a distância entre controles
isolados e um sistema operável de ponta a ponta sob concorrência, falha, múltiplos
workers e exigências de privacidade.

Os quatro eixos do parecer são:

- **Funcionalidade:** o núcleo existe, mas reemissão, gestão de usuários, auditoria,
  recuperação, progresso e perfis não formam fluxos completos no painel.
- **Privacidade e segurança:** há controles positivos, porém o download nominal e
  o pacote local anulam a minimização pretendida.
- **Confiabilidade:** constraints resolvem parte da idempotência, mas estados
  `failed`, templates concorrentes, jobs manuais e operações em startup deixam
  caminhos sem recuperação garantida.
- **Reprodutibilidade:** frontend e builds são reproduzíveis; backend e CI dependem
  de resolução dinâmica e omitem uma dependência necessária à suíte atual.

## 3. Pontos positivos comprovados

- **Sessões revogáveis no servidor:** cada JWT contém `jti` e depende de registro
  ativo em `auth_sessions`; logout e revogação invalidam a sessão
  (`certificados-admin/backEnd/auth.py:362-436`, `main.py:350-390`).
- **Cookies defensivos:** `HttpOnly`, `Secure` obrigatório em produção, `SameSite`
  validado e expiração definida (`auth.py:114-147`, `main.py:339-347`).
- **RBAC real no backend:** emissões, revogação, reemissão e ZIP exigem `admin` ou
  `secretaria`; templates mutáveis exigem `admin`; o auditor fica somente em rotas
  de leitura (`main.py:437-471`, `517-717`, `auth.py:439-448`).
- **CORS e origem:** produção rejeita `*`, exige HTTPS e valida `Origin`/`Referer`
  nas mutações autenticadas por cookie (`main.py:99-138`, `262-278`,
  `auth.py:483-509`).
- **Proteção de login distribuída:** throttle persistido por hash de IP e usuário,
  atraso progressivo, bloqueio temporário e verificação fictícia para usuário
  inexistente (`auth.py:200-214`, `280-356`).
- **Consultas parametrizadas:** a persistência usa SQLAlchemy com parâmetros e
  transações de commit/rollback (`database/engine.py:82-94`,
  `database/repositories.py`). Não foi localizado SQL formado a partir de entrada
  pública.
- **Idempotência parcial no banco:** `unique_code` e `business_key` são únicos e a
  reserva trata colisões concorrentes (`database/models.py:117-140`,
  `database/db.py:238-278`).
- **Integridade de arquivo:** downloads validam assinatura PDF, tamanho e SHA-256;
  divergência pode bloquear o registro (`storage_service/base.py:96-124`,
  `certificados-consulta/app.py:485-508`).
- **Drive privado proxiado:** o cliente recebe bytes, nunca uma URL do Drive
  (`storage_service/base.py:72-82`, `certificados-consulta/app.py:517-521`).
- **Minimização de documento:** o documento em claro é substituído por HMAC por
  padrão (`database/db.py:185-223`, `database/privacy.py:54-70`).
- **Preview sem persistência:** a pré-validação retorna relatório antes da rota de
  geração (`main.py:517-553`).
- **Validação inicial de XLSX:** há verificação OOXML, limite descomprimido,
  proporção, linhas, colunas, células e tempo na primeira leitura
  (`services/spreadsheet.py:208-281`).
- **Storage local contra traversal:** a implementação mantém caminhos sob a raiz e
  os testes de hardening passaram.
- **Frontend limpo:** `npm ci`, typecheck, testes e build passaram em cópia limpa
  com Node 20; o editor Fabric é lazy-loaded (`frontend/src/App.tsx:9`, `119-130`).
- **Modal acessível:** foco inicial, contenção de Tab, Escape e restauração de foco
  têm implementação e teste (`frontend/src/components/AccessibleModal.tsx`).
- **Container backend não-root e Compose endurecido:** backend usa `appuser`; a
  stack de produção usa filesystem somente leitura e `no-new-privileges`
  (`Dockerfile:28-30`, `compose.production.yaml:21-25`).

## 4. Arquitetura atual comprovada

```text
Painel React/Vite ──cookie──> nginx ──/api──> FastAPI admin ─┬─> PostgreSQL
                                                           └─> Google Drive

Navegador público ─────────> FastAPI + Jinja2 ─────────────┬─> mesmo PostgreSQL
                                                           └─> mesmo Google Drive

Alembic / seed / reconcile / integrity / backup ─────────────> recursos compartilhados
```

| Componente | Implementação atual | Evidência |
|---|---|---|
| Painel administrativo | React 19, TypeScript, Vite, Tailwind CSS, Axios, Fabric e Zustand | `certificados-admin/frontend/package.json:1-33` |
| API administrativa | FastAPI monolítico com rotas de auth, template, emissão, histórico e download | `certificados-admin/backEnd/main.py:237-817` |
| Aplicação pública | FastAPI, Jinja2 e CSS estático; busca, validação e download | `certificados-consulta/app.py:206-545` |
| Domínio/serviços | Planilha, texto, geração, saga, template, integridade e reconciliação | `certificados-admin/backEnd/services/` |
| Persistência | SQLAlchemy 2, repositórios, transações; SQLite dev/test e PostgreSQL produção | `database/engine.py:28-94`, `database/repositories.py` |
| Schema | 5 migrations Alembic; certificados, usuários, sessões, throttles, rate limit, auditoria e templates | `database/migrations/versions/0001...0005`, `database/models.py` |
| PDFs | Abstração local/Google Drive, metadados no banco, bytes proxiados | `storage_service/base.py`, `storage_service/google_drive.py` |
| Deploy | Docker/Compose/Caddy/nginx e scripts Cloud Run; GitHub Actions | `Dockerfile`, `compose.production.yaml`, `deploy/`, `.github/workflows/ci.yml` |

### Limites arquiteturais observados

- `main.py` tem 1.021 linhas, `certificados-consulta/app.py` 545,
  `database/db.py` 664 e `database/repositories.py` 901. A camada de rotas ainda
  concentra serialização, autorização, orquestração, ZIP e tratamento de erro.
- Diversos módulos alteram `sys.path`, por exemplo `main.py:6-18`, `auth.py:24-27`,
  `certificate_service.py:7-11`, `template_service.py:23-26` e
  `certificados-consulta/app.py:23-26`.
- O admin e a consulta compartilham banco, secret de HMAC e, no deploy atual,
  credencial do Drive. A consulta também executa escritas de rate limit, limpeza e
  preparação de dados.
- A saga cobre banco + storage por compensação, mas não há fila durável, worker ou
  máquina de estados que retome automaticamente toda falha.

## 5. Matriz de funcionalidades

| Funcionalidade | Afirmação/documento | Código e comportamento comprovado | Classificação |
|---|---|---|---|
| Login | README e PDF técnico | bcrypt, throttle, sessão persistida e cookie; testes de auth aprovados após ajuste temporário de dependência | **Implementado e comprovado** |
| Logout | README | revoga `jti` e remove cookie (`main.py:350-361`) | **Implementado e comprovado** |
| Sessões | README | expiração absoluta, revogação própria/global e validação no banco; sem timeout de inatividade efetivo | **Parcialmente implementado** |
| Perfis admin/secretaria/auditor | README | backend diferencia leitura/mutação; frontend mostra todas as abas a todos (`App.tsx:68-131`) | **Parcialmente implementado** |
| Upload XLSX | README/PDF | aceita `.xlsx`, limita 10 MB após leitura completa e valida OOXML (`main.py:186-209`) | **Implementado e comprovado** |
| Validação por linha | README/PDF | separa válidas/inválidas, mas só nome e carga são obrigatórios e faltam limites de domínio | **Parcialmente implementado** |
| Preview | README/PDF | mostra contagens, texto da primeira linha e até 50 linhas sem avisar truncamento (`EmitirCertificados.tsx:235-297`) | **Parcialmente implementado** |
| Emissão em lote | README/PDF | revalida e gera linhas válidas sequencialmente no request (`main.py:555-621`) | **Parcialmente implementado** |
| Prevenção de duplicidade | README/PDF | `business_key` único protege emissões normais; registro `failed` bloqueia retentativa | **Parcialmente implementado** |
| Geração PDF | README/PDF | Pillow renderiza em memória e storage recebe PDF; testes locais aprovados | **Implementado e comprovado** |
| QR Code | README/PDF | gera URL canônica, mas exceções de QR são ignoradas e template não é obrigado a conter QR (`generator.py:231-252`, `561-571`) | **Parcialmente implementado** |
| Histórico | README | lista paginada, status e disponibilidade (`main.py:625-656`) | **Implementado e comprovado** |
| Filtros | README | nome, código, curso, evento, status e ordenação existem; UI omite `pending`/`failed` | **Parcialmente implementado** |
| Download individual admin | README | autenticado, provider-agnostic e com integridade (`main.py:473-482`) | **Implementado e comprovado** |
| Download ZIP | README | seleção UI e limite de 200 na rota canônica; todos os PDFs e ZIP ficam em memória | **Parcialmente implementado** |
| Revogação | README/PDF | motivo obrigatório, RBAC e auditoria (`main.py:658-689`) | **Implementado e comprovado** |
| Reemissão | README/PDF | backend usa snapshot e troca arquivo; UI não oferece ação e status `failed` não é reativado | **Parcialmente implementado** |
| Editor de template | README | editor visual, fundo e elementos persistidos; overlays têm validação incompleta | **Parcialmente implementado** |
| Versionamento de template | README | versões imutáveis e ativação explícita; criação/ativação não são seguras sob concorrência | **Parcialmente implementado** |
| Validação pública por código/QR | README/PDF | HTML e JSON, status sanitizado e download de ativo (`app.py:377-425`) | **Implementado e comprovado** |
| Busca pública por nome | README | normalizada e paginada; expõe nome e metadados e o próprio autorizador de download | **Parcialmente implementado** |
| Confirmação por documento/matrícula | README | função de comparação existe, mas não é chamada pelo download nominal | **Apenas documentado** |
| Auditoria | README | grava ações e incidentes; não há rota/tela de consulta, política de retenção ou exportação | **Parcialmente implementado** |
| Métricas | README | endpoint autenticado e contadores em memória por processo (`observability/__init__.py:82-111`) | **Parcialmente implementado** |
| Gestão de usuários | Contexto/PDF | repositório e CLI criam/ativam/trocam papel; API só revoga sessões; não há UI CRUD | **Parcialmente implementado** |
| Alteração/recuperação de senha | Contexto/PDF | não há rota, UI, token de recuperação nem fluxo de troca | **Ausente** |
| Backup | README/docs | perfil Compose e comandos manuais; agendamento é instrução operacional | **Parcialmente implementado** |
| Restauração | README/docs | procedimento escrito; não existe automação nem teste | **Apenas documentado** |
| Reconciliação Drive | README/docs | CLI e serviço existem, com fakes; execução periódica real não está configurada | **Parcialmente implementado** |
| Reparação de emissão interrompida | README/docs | `reconcile.py` trata alguns estados, mas depende de cron externo e não libera `business_key` de `failed` | **Parcialmente implementado** |
| Integridade periódica | README/docs | CLI e verificação em download existem; cron/staging real não comprovados | **Parcialmente implementado** |
| CI/CD | README | lint, compile, SQLite, pytest, build e gitleaks existem; há lacunas e audits não bloqueiam | **Parcialmente implementado** |

## 6. Divergências entre documentação e implementação

| Afirmação histórica | Evidência atual | Conclusão |
|---|---|---|
| Busca nominal exige documento ou matrícula (`README.md:61-68`, `354-356`) | formulário envia apenas nome e `download_challenge`; endpoint valida somente esses dois campos (`index.html:81-84`, `app.py:456-472`) | Afirmação incorreta e risco P0. |
| Serviço público não recebe credencial administrativa do Drive (`app.py:231-238`, `DEPLOY_E_RECUPERACAO.md:47-55`) | `COMMON_ENV`/`COMMON_SECRETS` e âncora Compose entregam o mesmo token a admin e consulta (`deploy.sh:38-39`, `56-88`; `compose.production.yaml:3-18`) | Separação prometida não implementada. |
| Curso, evento e data de emissão são obrigatórios (`README.md:315-327`) | somente `nome` e `carga_horaria` são obrigatórios; curso desconhecido e data inválida são preservados (`spreadsheet.py:7-19`, `64`, `313-359`) | Contrato público diverge do validador. |
| Datas persistidas são sempre ISO (`README.md:329-332`, `ARQUITETURA.md:35`) | emissão usa `to_iso(...) or valor_original`, inclusive vazio/legado (`certificate_service.py:192-195`) | Não há garantia no domínio/schema. |
| Exatamente um template ativo (`ARQUITETURA.md:49-51`) | não há índice único parcial; ativação faz dois `UPDATE` sem lock (`models.py:279-292`, `repositories.py:849-866`) | Falso sob concorrência. |
| Reparos “assíncronos” (`ARQUITETURA.md:47`) | são CLIs dependentes de cron externo, sem scheduler/fila no deploy | Terminologia superestima a implementação. |
| Logs nunca contêm PII (`ARQUITETURA.md:27`, `63`; `README.md:796-803`) | storage registra nome de arquivo e IDs; login registra username; migration 0005 registra valor de data não convertido (`google_drive.py:137-146`, `auth.py:255-277`, migration `0005:71-100`) | Política não é cumprida de modo uniforme. |
| Todos os achados críticos/altos foram resolvidos (`RELATORIO_FINAL_IMPLEMENTACAO.md:53`) | fluxo nominal, pacote, Drive, proxy, concorrência e retentativa permanecem | Relatório histórico não descreve o estado comprovado. |
| Suíte histórica: 166 aprovados/3 ignorados (`RELATORIO_FINAL_IMPLEMENTACAO.md:120`) | dependências declaradas falham na coleta; com dependência temporária foram 197 aprovados/3 ignorados | Número histórico não é reproduzível com o manifesto atual. |
| CI executa auditorias e qualidade do frontend (`README.md:782-792`) | audits têm `continue-on-error`; frontend CI não roda `npm test` (`ci.yml:68-76`) | Falhas relevantes não bloqueiam merge. |
| Constraints/idempotência suportam múltiplos workers (`DEPLOY_PRODUCAO_DUAL.md:148-149`) | templates falham sob concorrência e `failed` envenena a chave de negócio | Afirmação ampla demais. |
| Conteúdo sensível nunca entra no build (`.dockerignore:14-35`, `.gcloudignore:7-39`) | build limpo observado continha `backEnd/data/participantes.xlsx`; `Dockerfile:23` copia todo o contexto | Padrões não protegem o arquivo aninhado rastreado. |

## 7. Problemas encontrados por prioridade

### RT-01 — Pacote de entrega contém segredos e artefatos de dados

- **Prioridade:** P0 — corrigir antes de compartilhar ou publicar.
- **Evidência:** `.gitignore:10-22`, `29-45`, `53-57`; caminhos locais `.env`,
  `secrets/google_oauth_token.json`, `secrets/service_account.json`; arquivo
  rastreado `certificados-admin/backEnd/data/participantes.xlsx`.
- **Comportamento observado:** o ZIP adjacente ao projeto passou no CRC, mas contém
  23.352 entradas, incluindo 1 `.env`, 2 arquivos com nome de credencial, 2 bancos,
  4 WAL/SHM, 2 planilhas, 18 PDFs, 22 logs, 2 arquivos compactados aninhados,
  4.871 itens de `.git`, 17.847 de `node_modules` e 197 caches. Nenhum valor ou dado
  pessoal foi aberto. Não é possível afirmar se as credenciais são válidas.
- **Impacto:** exposição de credencial, dados pessoais e histórico local; entrega de
  centenas de MB; risco institucional e incompatibilidade com minimização/LGPD.
- **Correção recomendada:** retirar o ZIP de circulação; presumir comprometimento e
  rotacionar/revogar credenciais por procedimento institucional; confirmar que a
  planilha rastreada é 100% sintética ou removê-la do histórico; gerar entrega por
  allowlist a partir de clone limpo/`git archive`, nunca compactando o diretório de
  trabalho.
- **Teste de correção:** inspecionar somente a lista do novo ZIP e exigir zero
  `.env`, secrets, bancos, WAL/SHM, dados, PDFs gerados, logs, caches,
  `node_modules`, `dist` e `.git`; scanner redigido deve retornar zero segredo real.

### RT-02 — Repositório Git e working tree contaminados por duplicatas `(2)`

- **Prioridade:** P0.
- **Evidência:** `git status` registra 152 arquivos não rastreados com sufixo `(2)`;
  há 2.245 duplicatas dentro de `.git`; `git fsck --full --strict --no-reflogs`
  retorna código 10 com referências/objetos inválidos.
- **Comportamento observado:** existe uma segunda cópia quase integral de fontes,
  testes, docs e configurações, inclusive ` (2).env`. Os arquivos comparados eram
  byte a byte iguais ao canônico. O `HEAD` alcançável foi validado e não havia
  modificação rastreada, mas a integridade global de `.git` falha.
- **Impacto:** fonte ambígua, risco de editar/entregar a cópia errada, scanner e IDE
  com resultados duplicados, repositório não confiável para avaliação.
- **Correção recomendada:** preservar backup forense, criar clone limpo do remoto ou
  exportar o `HEAD` validado, recuperar somente mudanças legítimas e substituir a
  pasta contaminada. Não tentar “limpar” `.git` manualmente sem backup.
- **Teste de correção:** `git fsck --full --strict`, `git status` e busca por `(2)`
  devem retornar integridade limpa e nenhuma duplicata indevida.

### RT-03 — A busca nominal fornece o próprio autorizador do download

- **Prioridade:** P0.
- **Evidência:** `certificados-consulta/app.py:125-135`, `456-472`;
  `database/privacy.py:61-70`; `certificados-consulta/templates/index.html:81-84`;
  promessa contrária em `README.md:354-356`.
- **Comportamento observado:** cada resultado contém `download_challenge`, um HMAC
  determinístico apenas do código. O formulário reenvia nome + challenge e o
  backend libera o PDF. `hash_matches_document` existe, mas não participa do fluxo.
  O challenge não expira, não é de uso único e não é ligado a uma confirmação
  independente.
- **Impacto:** qualquer pessoa que obtenha um resultado nominal pode baixar um PDF
  com dados pessoais; a minimização da resposta não protege o arquivo final.
- **Correção recomendada:** exigir fator independente já registrado, como documento
  ou matrícula normalizado e comparado por HMAC; emitir token aleatório de curta
  duração, vinculado ao certificado e à confirmação, armazenado no servidor e de
  uso único; manter respostas neutras e bloqueio/rate limit.
- **Teste de correção:** resultado/challenge sozinho deve receber 403/404; prova
  incorreta deve falhar sem revelar existência; prova correta deve gerar token
  curto; segundo uso e token expirado devem falhar.

### RT-04 — Busca por nome usa GET e expõe um diretório nominal

- **Prioridade:** P0.
- **Evidência:** `templates/index.html:5-18`, `92-99`; `app.py:279-349`, `428-448`;
  `app.py:215-227` aplica `no-store` somente a `/validar/`; `deploy/Caddyfile:6-11`.
- **Comportamento observado:** o nome fica em query string e paginação. A resposta
  mostra nome completo, curso, evento, carga, data e status. Não há `Cache-Control:
  no-store` específico para busca. O logger da aplicação omite query, mas Caddy,
  nginx, plataforma, navegador e intermediários não possuem regra de redação
  comprovada.
- **Impacto:** exposição e retenção de nomes e vínculos acadêmicos em histórico,
  cache, favoritos, Referer e logs; enumeração de certificados por termos curtos.
- **Correção recomendada:** usar POST para consulta nominal, não refletir o nome na
  URL, aplicar `Cache-Control: no-store, private`, `Pragma: no-cache` e
  `Referrer-Policy: no-referrer`; reduzir os campos antes da confirmação e redigir
  queries nos proxies/observabilidade.
- **Teste de correção:** URL e logs sintéticos não podem conter o termo; respostas
  devem ter cabeçalhos de não armazenamento; busca parcial não deve listar um
  diretório de pessoas.

### RT-05 — Consulta pública recebe credencial do Drive com escrita

- **Prioridade:** P0.
- **Evidência:** `storage_service/google_drive.py:35-36`, `109-157`, `226-250`;
  `deploy/cloudrun/deploy.sh:38-39`, `56-88`; `compose.production.yaml:3-18`,
  `39-69`; documentação promete leitor separado em
  `docs/DEPLOY_E_RECUPERACAO.md:47-55`.
- **Comportamento observado:** `drive.file` permite criar e excluir arquivos do
  aplicativo. Admin e consulta recebem o mesmo token OAuth e usam a mesma classe,
  que implementa `save` e `delete`. Não foi acessado o Drive nem validado o IAM real.
- **Impacto:** comprometimento da superfície pública pode atingir disponibilidade e
  integridade dos certificados, não somente leitura.
- **Correção recomendada:** credenciais distintas; admin com permissão estritamente
  necessária e consulta com identidade somente-leitura sobre pasta/Shared Drive;
  separar também papéis de banco conforme as escritas públicas necessárias;
  rotacionar o token compartilhado após a mudança.
- **Teste de correção:** em staging, a identidade pública deve baixar arquivo
  permitido e receber negação ao criar, alterar, mover ou excluir; configuração
  deve provar secrets diferentes por serviço.

### RT-06 — Cabeçalhos de proxy são confiados de qualquer origem

- **Prioridade:** P0 para publicação pública; P1 para demonstração isolada.
- **Evidência:** `deploy/entrypoint.sh:18-29`, `compose.production.yaml:52-69`,
  `docs/DEPLOY_PRODUCAO.md:78-80`; consumidores em `auth.py:238-247` e
  `certificados-consulta/app.py:154-180`.
- **Comportamento observado:** Uvicorn usa `--forwarded-allow-ips="*"`. Assim, o
  `request.client` já pode ter sido reescrito antes das validações internas, mesmo
  quando `TRUSTED_PROXY_CIDRS` está vazio.
- **Impacto:** atribuição incorreta de IP, evasão/fragmentação de rate limit,
  bloqueio abusivo e trilha de auditoria imprecisa.
- **Correção recomendada:** aceitar cabeçalhos somente do proxy imediato conhecido,
  remover cabeçalhos recebidos do cliente na borda e documentar cadeia de proxies
  por ambiente. Em Cloud Run, validar a topologia oficial e não usar `*`.
- **Teste de correção:** testes ASGI atrás de proxy local devem provar que header de
  cliente direto é ignorado e que apenas o proxy allowlisted define o IP; limites
  distribuídos devem permanecer efetivos.

### RT-07 — A suíte backend não é reproduzível com dependências declaradas

- **Prioridade:** P1.
- **Evidência:** `certificados-admin/backEnd/requirements.txt:1-21`,
  `certificados-consulta/requirements.txt:1-9`, `.github/workflows/ci.yml:22-27`,
  `43-45`.
- **Comportamento observado:** em Python 3.12 limpo, instalação dos dois manifests
  concluiu, mas `pytest` falhou na coleta porque o `TestClient` atual exige
  `httpx2`, não declarado. Após instalar `httpx2` somente no ambiente descartável,
  o resultado foi 197 aprovados e 3 ignorados. As faixas amplas resolvem versões
  diferentes ao longo do tempo e não há requirements de desenvolvimento ou hashes.
- **Impacto:** CI pode quebrar sem mudança no repositório; o resultado histórico não
  é reproduzível; risco de supply chain e apresentação sem setup determinístico.
- **Correção recomendada:** criar manifesto/lock de runtime e de desenvolvimento,
  declarar todas as dependências de teste, alinhar Python 3.12/Ruff e usar hashes ou
  mecanismo de lock suportado.
- **Teste de correção:** container Python 3.12 sem cache deve instalar manifests e
  executar `pip check`, compile, Ruff, migrations e toda a suíte sem instalação
  suplementar.

### RT-08 — Uma falha de emissão bloqueia a retentativa idempotente

- **Prioridade:** P1.
- **Evidência:** reserva retorna qualquer `business_key` existente
  (`database/db.py:255-274`); compensação mantém a linha e marca `failed`
  (`certificate_service.py:295-349`, `repositories.py:157-178`); reemissão atualiza
  apenas metadados do arquivo (`repositories.py:274-290`).
- **Comportamento observado:** teste de regressão descartável confirmou: após falha,
  reenviar o mesmo lote retorna “duplicado” apontando ao registro `failed`; reemitir
  o registro grava arquivo, mas mantém status `failed`.
- **Impacto:** certificado legítimo pode ficar irrecuperável pela interface, retries
  automáticos não convergem e banco/storage podem divergir.
- **Correção recomendada:** definir política explícita de retry para `failed` com
  transição atômica para `pending`, contador/tentativa e lease; ou gerar nova chave
  vinculada ao incidente. Reemissão deve transicionar estado de modo validado.
- **Teste de correção:** falhar uma tentativa com storage fake, repetir e comprovar
  exatamente um registro `ativo`, um arquivo e auditoria da recuperação; repetir
  concorrente sem duplicar.

### RT-09 — Criação e ativação de templates têm condição de corrida

- **Prioridade:** P1.
- **Evidência:** versão calculada por `max()+1`
  (`database/repositories.py:776-807`); ativação em dois updates sem lock
  (`repositories.py:849-866`); só há índice comum de `is_active`
  (`database/models.py:265-292`).
- **Comportamento observado:** no PostgreSQL efêmero, 12 criações concorrentes
  produziram somente 4–5 sucessos e 7–8 `IntegrityError`; ativações simultâneas a
  partir de estado sem ativo terminaram com duas versões ativas.
- **Impacto:** erro 500 para administradores, emissão com template não determinístico
  e quebra da promessa de uma única versão ativa.
- **Correção recomendada:** gerar versão com sequence/lock/retry; serializar ativação
  e adicionar índice único parcial `WHERE is_active=1` no PostgreSQL, com estratégia
  equivalente de domínio/teste no SQLite.
- **Teste de correção:** dezenas de criações/ativações concorrentes devem terminar
  sem erro não tratado, números únicos e exatamente um ativo.

### RT-10 — Contrato e validação da planilha aceitam dados incompatíveis

- **Prioridade:** P1.
- **Evidência:** `spreadsheet.py:7-19`, `64`, `149-154`, `313-359` versus
  `database/models.py:55-65`; README em `315-327`.
- **Comportamento observado:** só nome/carga são obrigatórios; carga extrai o primeiro
  grupo de dígitos; curso desconhecido, evento vazio, datas inválidas e strings
  acima dos limites das colunas podem entrar como linha válida. O limite de célula
  (2.000) excede vários `VARCHAR(64/255)`. A reserva ocorre antes do `try` da saga.
- **Impacto:** preview afirma que linha está apta e a geração/DB pode rejeitá-la;
  certificados academicamente incompletos ou inconsistentes; lote parcialmente
  processado.
- **Correção recomendada:** definir schema único para preview e persistência;
  validar obrigatoriedade, tamanho, carga positiva/range, e-mail/documento, curso,
  evento e datas ISO; rejeitar coluna duplicada ambígua e valores não normalizáveis.
- **Teste de correção:** testes de fronteira devem comprovar que tudo marcado válido
  persiste/renderiza e tudo fora do domínio aparece no preview com linha/campo.

### RT-11 — Geração e ZIP são síncronos e mantêm todo o conteúdo em memória

- **Prioridade:** P1.
- **Evidência:** loop síncrono `certificate_service.py:173-245`; rota `async` chama
  geração diretamente (`main.py:581-596`); ZIP acumula lista + `BytesIO`
  (`main.py:714-765`, `767-815`); Drive baixa para `BytesIO`
  (`google_drive.py:159-189`); cliente usa timeouts de 60/120 s (`api.ts:27-31`,
  `206-224`).
- **Comportamento observado:** cada request ocupa worker durante render/upload; ZIP
  mantém PDFs individuais e cópia compactada. Não há job id, progresso real,
  cancelamento, lease ou retomada. Timeout do cliente não cancela o trabalho.
- **Impacto:** memória e latência crescem com lote; cold start/timeout pode deixar
  `pending`; retry do usuário pode colidir ou produzir resultado confuso; custo de
  Cloud Run e indisponibilidade sob concorrência.
- **Correção recomendada:** fila/job durável, processamento assíncrono idempotente,
  estado/progresso e retomada; stream de downloads e ZIP para arquivo temporário ou
  storage com limite total de bytes; cancelamento/timeout alinhados.
- **Teste de correção:** carga concorrente com lotes máximos deve respeitar teto de
  memória/tempo, sobreviver a interrupção de worker e retomar sem duplicação.

### RT-12 — CI não representa o conjunto de qualidade necessário

- **Prioridade:** P1.
- **Evidência:** `.github/workflows/ci.yml:12-88`.
- **Comportamento observado:** frontend CI executa build, não `npm test`; audits são
  não bloqueantes; migrations só em SQLite; não há PostgreSQL, Compose/build de
  imagem, contratos, E2E, acessibilidade, concorrência, backup/restore ou staging
  Drive. Actions usam tags móveis. Ruff mira Python 3.11 (`ruff.toml:1-3`) enquanto
  CI/Docker usam 3.12.
- **Impacto:** merge pode aceitar regressão já detectável; green build não prova o
  que README afirma; supply chain e compatibilidade ficam implícitas.
- **Correção recomendada:** adicionar jobs bloqueantes para testes frontend,
  PostgreSQL/Alembic, Compose/build, segurança definida pela instituição e E2E;
  fixar actions por SHA; alinhar Python 3.12; tornar checks required no provedor.
- **Teste de correção:** PR deliberadamente quebrado em cada camada deve bloquear;
  lista local dos workflows deve corresponder aos checks obrigatórios configurados.

### RT-13 — Metadata Alembic diverge no PostgreSQL e migrations não são expand/contract

- **Prioridade:** P1.
- **Evidência:** índice GIN criado por SQL em migration `0004:35-40`, ausente dos
  modelos; migration `0005:71-145` lê/atualiza tabela inteira, cria índice e altera
  constraints; CI testa só SQLite (`ci.yml:35-41`).
- **Comportamento observado:** upgrade/downgrade/reupgrade passou em PostgreSQL 16
  efêmero, mas `alembic check` propôs remover
  `idx_certificates_name_normalized_trgm`. A migration 0005 pode bloquear tabela e
  registra valores de datas não convertidas.
- **Impacto:** falso drift, mudança destrutiva acidental, locks em rollout e PII em
  logs de migration.
- **Correção recomendada:** declarar/filtrar corretamente o índice no metadata,
  testar autogenerate em PostgreSQL e migrar por expand/backfill em lotes/contract;
  criar índices grandes de forma compatível com o banco e não logar valores reais.
- **Teste de correção:** banco PostgreSQL efêmero em cada PR deve fazer
  upgrade→check sem diff→downgrade suportado→upgrade, com volume representativo e
  verificação de locks/logs.

### RT-14 — Startup modifica dados e readiness verifica somente o banco

- **Prioridade:** P1.
- **Evidência:** admin executa init, varredura de dados, seed, cleanup e template no
  startup (`main.py:237-250`); consulta faz init, varredura e cleanup
  (`certificados-consulta/app.py:253-261`); readiness só chama banco
  (`main.py:298-305`, `app.py:269-276`).
- **Comportamento observado:** `prepare_private_data` carrega todos os certificados
  (`database/db.py:185-223`) em cada processo/rollout. O serviço público exige
  escrita. Readiness não prova storage, template ativo, versão de schema ou
  capacidade de gerar/baixar.
- **Impacto:** startup lento/concorrente, rollout com mutações repetidas, instância
  “ready” sem Drive/template e indisponibilidade difícil de diagnosticar.
- **Correção recomendada:** migrations/backfills/seeds como jobs idempotentes de
  release; startup somente valida configuração; readiness separada para DB, schema,
  storage e dependências essenciais com orçamento de timeout.
- **Teste de correção:** múltiplas instâncias devem iniciar em paralelo sem writes;
  readiness deve falhar de forma sanitizada quando cada dependência essencial é
  isoladamente indisponível.

### RT-15 — Gestão de usuários, senha e auditoria não formam um produto administrável

- **Prioridade:** P1.
- **Evidência:** API só revoga sessões de outro usuário (`main.py:386-405`); CRUD
  existe apenas em `database/db.py:443-473`; CLI aceita senha em argumento
  (`create_admin.py:3-5`, `21-27`); `LoginRequest` não impõe limites/política
  (`main.py:150-152`); logs de auditoria só têm repositório (`db.py:642-662`).
- **Comportamento observado:** não há listar/criar/desativar usuários no painel,
  troca/recuperação de senha, expiração de senha, segundo fator, visualização da
  trilha ou retenção. O lockout por usuário também pode indisponibilizar conta
  conhecida. `last_seen_at` existe, mas não é atualizado.
- **Impacto:** dependência de operador/CLI, senha potencialmente exposta em shell,
  recuperação insegura/manual e auditor sem ferramenta de auditoria.
- **Correção recomendada:** ciclo de vida administrativo com política de senha,
  troca autenticada, recuperação com token curto e uso único, MFA para admin,
  desativação/revogação, UI de auditoria read-only e retenção; preferir prompt/stdin
  na CLI e mecanismo de desbloqueio controlado.
- **Teste de correção:** matriz por papel, criação/desativação, troca/reset, sessões
  revogadas, token expirado/reutilizado, lockout e consulta de auditoria sem PII
  indevida.

### RT-16 — Frontend não aplica RBAC nem expõe todos os fluxos do backend

- **Prioridade:** P1.
- **Evidência:** todas as abas são renderizadas independentemente de `user.role`
  (`frontend/src/App.tsx:68-131`); histórico importa somente download/list/revoke
  (`Historico.tsx:1-10`); função de reemissão existe, mas não é usada
  (`api.ts:255-259`); resumo TS omite `failed`/`failed_count`
  (`api.ts:109-117`) embora backend os retorne (`main.py:608-620`).
- **Comportamento observado:** auditor vê controles que resultarão em 403;
  secretaria vê editor que apenas admin altera; não há tela de auditoria/usuários;
  reemissão é backend-only; falhas individuais de geração desaparecem do resumo.
- **Impacto:** experiência incoerente, decisões operacionais erradas e falsa
  impressão de que todas as linhas válidas foram emitidas.
- **Correção recomendada:** política de capabilities derivada do papel, navegação e
  controles coerentes com backend; telas read-only do auditor; ação de reemissão
  confirmada; mostrar falhas com linha/motivo e opção segura de recuperação.
- **Teste de correção:** testes de componentes/E2E para cada papel e cada resposta
  401/403/failed; nenhuma ação proibida deve aparecer ou ser acionável.

### RT-17 — Empacotamento e containers carregam superfície desnecessária

- **Prioridade:** P1 para dados; P2 para hardening.
- **Evidência:** `Dockerfile:23` usa `COPY . /app`; padrões de ignore usam
  `data/`/`*.xlsx` sem garantir recursão (`.dockerignore:14-22`,
  `.gcloudignore:31-39`); Dockerfiles web não definem `USER`
  (`deploy/Dockerfile.web:12-15`, `Dockerfile.cloudrun-web:14-23`); imagens usam tags
  móveis.
- **Comportamento observado:** imagem backend construída do `HEAD` continha
  `certificados-admin/backEnd/data/participantes.xlsx` e testes. Backend roda como
  `appuser`; nginx roda com usuário padrão da imagem. Não foi lido o XLSX.
- **Impacto:** PII potencial dentro de camada distribuída, imagem maior, mais
  superfície e permissões superiores no web container.
- **Correção recomendada:** contextos/`COPY` por allowlist, remover dado rastreado,
  padrões `**`, imagem runtime mínima, usuário nginx não-root, filesystem read-only
  também no web/gateway e pin por digest com processo de atualização.
- **Teste de correção:** inspecionar filesystem/SBOM local da imagem e exigir zero
  dados/testes/secrets; `docker inspect` deve mostrar UID não-root e digest imutável.

### RT-18 — Hardening HTTP, documentação de API, TLS de banco e logs são inconsistentes

- **Prioridade:** P1 para produção.
- **Evidência:** FastAPI usa URLs padrão de docs (`main.py:252-256`,
  `certificados-consulta/app.py:206-210`); nginx Cloud Run não define CSP/HSTS
  (`nginx.cloudrun.conf:1-13`); Caddy define HSTS, mas serviços Cloud Run são
  `--allow-unauthenticated` (`deploy.sh:56-100`); engine não força SSL
  (`database/engine.py:56-58`, `database/config.py:160-175`); Drive registra filename
  e IDs (`google_drive.py:137-146`, `181-187`, `241-249`).
- **Comportamento observado:** `/docs`, `/redoc` e `/openapi.json` permanecem
  habilitados por padrão; CSP/HSTS dependem do caminho de entrada; TLS PostgreSQL
  depende de `sslmode` fornecido pelo operador; logs podem conter nome por filename
  e localizadores internos.
- **Impacto:** metadados de API expostos, proteção desigual em URLs diretas,
  conexão de banco sem política fail-closed se URL for mal configurada e retenção
  desnecessária de identificadores/PII em logs.
- **Correção recomendada:** desativar/restringir docs em produção; aplicar headers
  consistentes na borda e app, incluindo CSP `frame-ancestors`, HSTS e
  Permissions-Policy; exigir TLS verificável para PostgreSQL; logar IDs de evento
  pseudônimos e redigir filenames/IDs/erros de provedor.
- **Teste de correção:** testes de headers em todas as origens, docs 404/403 em
  produção, startup recusando URL PostgreSQL sem política TLS e assertions de logs
  sintéticos sem nome/documento/filename/token.

### RT-19 — Retenção e direitos dos titulares não estão implementados

- **Prioridade:** P1 para produção; P2 para demonstração sintética.
- **Evidência:** limpeza opcional remove e-mail/documento, mas preserva nome,
  metadados, PDF e auditoria indefinidamente (`database/db.py:185-223`);
  `AuditLog` não possui expiração (`database/models.py:232-253`).
- **Comportamento observado:** não há política executável para retenção, descarte,
  anonimização, acesso/correção, base legal, responsáveis ou registro de consentimento
  quando aplicável. PDFs e backups não participam de um workflow de exclusão.
- **Impacto:** violação dos princípios de necessidade, minimização, segurança e
  limitação de conservação; dificuldade de atender solicitação institucional.
- **Correção recomendada:** inventário de dados, finalidade/base legal, prazos por
  categoria, rotina aprovada de retenção/anonimização e procedimento de titular;
  alinhar DB, Drive, logs e backups, preservando obrigações acadêmicas/auditoria.
- **Teste de correção:** dados sintéticos acima do prazo devem ser tratados em todos
  os storages conforme política, com exceções legais auditadas e restauração que não
  ressuscite dados expirados.

### RT-20 — Imagens de overlay e QR podem produzir certificado sem validação suficiente

- **Prioridade:** P2.
- **Evidência:** limites só somam tamanho textual das data URLs
  (`template_service.py:88-102`); overlays são decodificados/abertos sem os limites
  aplicados ao fundo e dimensões vêm do layout (`generator.py:532-585`); falha de QR
  é ignorada (`generator.py:246-252`, `564-571`).
- **Comportamento observado:** fundo passa por `Image.verify` e limite de pixels,
  overlays não; elementos podem pedir redimensionamentos extremos. A geração pode
  concluir sem QR e o schema não exige elemento QR.
- **Impacto:** consumo excessivo de memória por admin autenticado/erro de template e
  certificado sem o mecanismo de validação prometido.
- **Correção recomendada:** validar toda imagem incorporada com magic, tamanho,
  pixels e dimensões; limitar coordenadas/dimensões; exigir QR em template ativo e
  tornar erro de geração explícito; validar URL e decodabilidade após render.
- **Teste de correção:** corpus de imagens truncadas/bombas/dimensões extremas deve
  ser rejeitado e todo PDF aprovado deve conter QR decodificável para a URL esperada.

### RT-21 — Modelo de dados não expressa invariantes importantes

- **Prioridade:** P2.
- **Evidência:** `template_version_id`, `created_by`, `activated_by` e
  `auth_sessions.user_id` não têm FK (`database/models.py:93`, `175-190`,
  `286-288`); datas são strings e workload não tem check (`models.py:55-65`);
  `is_active`/`integrity_blocked` são inteiros sem check.
- **Comportamento observado:** parte da consistência depende somente da aplicação;
  registros órfãos, datas inválidas e flags fora de 0/1 são possíveis por script ou
  falha de versão.
- **Impacto:** drift silencioso, joins sem integridade e reconciliação mais complexa.
- **Correção recomendada:** FKs com política de delete explícita, tipos `DATE` e
  booleanos, checks de range e índice único parcial do template; migração
  expand/contract e limpeza prévia.
- **Teste de correção:** testes PostgreSQL devem rejeitar cada estado inválido e
  validar upgrades com dados legados representativos.

### RT-22 — Responsabilidades e imports dificultam manutenção e teste isolado

- **Prioridade:** P2.
- **Evidência:** tamanhos registrados na seção 4; manipulação de `sys.path` em
  `main.py:6-18`, `auth.py:24-27`, `template_service.py:23-26` e outros módulos.
- **Comportamento observado:** rotas são closures de `create_app`, há fachadas
  duplicadas em `database/db.py`, e imports dependem da posição de execução.
- **Impacto:** acoplamento, mocks amplos, import order frágil, onboarding difícil e
  refatorações arriscadas.
- **Correção recomendada:** empacotar o projeto Python, usar imports absolutos,
  `APIRouter`, schemas, services/repositories injetados e unidade de trabalho por
  caso de uso; separar consultas públicas read-only.
- **Teste de correção:** módulos devem importar a partir de qualquer cwd sem alterar
  `sys.path`; testes de routers/services devem rodar isoladamente.

### RT-23 — Readiness, jobs, métricas e recuperação não fecham a operação

- **Prioridade:** P2, bloqueador de produção.
- **Evidência:** métricas são dicionário em processo (`observability:82-111`);
  backup é profile manual (`compose.production.yaml:122-134`); jobs só aparecem em
  documentação/CLI; README reconhece métricas por instância (`README.md:815-816`).
- **Comportamento observado:** não há scheduler comprovado, exportador consolidado,
  alerta, SLO, retenção automática de backup, teste de restore ou RPO/RTO executável.
  O healthcheck não detecta todas as dependências.
- **Impacto:** múltiplos workers mostram métricas divergentes; incidentes podem ser
  detectados tarde; recuperação permanece uma hipótese documental.
- **Correção recomendada:** métricas externas, logs redigidos, tracing/alertas,
  scheduler único com locks, backups cifrados fora do domínio de falha, retenção,
  restore periódico e runbooks com RPO/RTO/responsáveis.
- **Teste de correção:** exercício automatizado restaura backup em ambiente isolado,
  reconcilia storage e mede RPO/RTO; falhas de jobs geram alerta e métricas agregam
  todas as instâncias.

### RT-24 — Acessibilidade, responsividade e estados de produto não têm prova suficiente

- **Prioridade:** P1 para apresentação; P2 para conformidade WCAG 2.2 AA.
- **Evidência:** tablist sem `aria-controls`, IDs ou navegação por setas
  (`App.tsx:91-159`); itens clicáveis são `<li>` sem teclado e ações só aparecem em
  hover (`ElementList.tsx:78-120`); editor reserva painéis de 208+240 px
  (`ElementList.tsx:37`, `PropertiesPanel.tsx:49-65`); CSS global não define
  `focus-visible`/`prefers-reduced-motion` (`index.css:1-43`).
- **Comportamento observado:** por inspeção estática, a barra de quatro abas `w-fit`
  não quebra em 320 px; o editor é impraticável em 320/768 px e denso em 1024 px;
  em 1440 px o container de 6xl é adequado. Offline e progresso de geração não têm
  estado dedicado. Não houve medição dinâmica de contraste, leitor de tela ou
  viewport, portanto WCAG AA não está comprovada.
- **Impacto:** usuários de teclado/touch/leitor de tela podem não operar editor e
  navegação; apresentação mobile pode quebrar; erro/timeout parece travamento.
- **Correção recomendada:** tabs WAI-ARIA completas, foco visível global, elementos
  semânticos, ações sempre acessíveis a foco/touch, editor responsivo por drawers,
  estados offline/timeout/progresso e auditoria WCAG 2.2 AA.
- **Teste de correção:** Playwright + axe nos viewports 320, 768, 1024 e 1440;
  roteiro manual somente teclado, zoom 200/400%, contraste e leitores NVDA/VoiceOver.

## 8. Privacidade e configuração defensiva

### Modelo de ameaças defensivo

| Ativo | Atores/entrada | Limite de confiança | Controles atuais | Lacuna principal |
|---|---|---|---|---|
| PDFs e dados acadêmicos | público, secretaria | navegador público → consulta | status, rate limit, integridade, proxy privado | busca nominal autoriza download e expõe metadados |
| Sessões administrativas | usuário, navegador, proxy | painel/nginx → admin | bcrypt, cookie, sessão revogável, Origin/CORS, throttle | proxy irrestrito, sem MFA/ciclo de senha |
| Banco/metadados | duas APIs, jobs | app → PostgreSQL | ORM, transações, constraints | TLS não imposto, consulta faz writes, invariantes ausentes |
| Drive | admin, consulta, jobs | app → Google API | pasta privada, `drive.file`, checksum | mesma credencial com escrita na superfície pública |
| Templates/uploads | admin/secretaria | navegador autenticado → render | limites de fundo/XLSX | overlays, corrida de ativação, worker síncrono |
| Auditoria/logs/backups | operadores/plataforma | app → stdout/volume/provedor | JSON/correlation id | filename/IDs/username, retenção e restore não definidos |
| Supply chain/entrega | Git, npm/pip, Docker, CI | desenvolvedor → build/merge | lock npm, CI, gitleaks | Python sem lock, checks incompletos, pacote contaminado |

### Revisão por categoria

- **Autenticação/sessão:** controles centrais são adequados como base, mas faltam
  MFA, política/ciclo de senha e timeout ocioso; lockout por usuário precisa de
  procedimento de desbloqueio para não virar indisponibilidade.
- **CSRF/CORS:** a validação de Origin/Referer e a allowlist CORS são pontos fortes.
  Devem permanecer cobertas por testes ao introduzir novos proxies/domínios.
- **XSS/injeção/path traversal/SSRF:** Jinja usa autoescape, React escapa texto,
  queries são parametrizadas e storage local restringe caminhos. Não foi localizada
  busca remota controlada pelo usuário. Isso reduz risco, mas não substitui testes
  de regressão e CSP.
- **Uploads:** há base defensiva para XLSX e fundo; faltam limite de número de
  entradas ZIP, prazo cobrindo o segundo parse Pandas, limite antes de ler todo o
  body e validação equivalente para overlays.
- **Enumeração:** código possui entropia aleatória, mas busca parcial nominal lista
  pessoas e rate limit depende do IP confiável. Mensagens por código distinguem
  estados deliberadamente; a política de exposição deve ser institucional.
- **Erros:** respostas principais escondem detalhes internos, porém logs capturam
  exceções e localizadores; auditoria também armazena `str(exc)` em alguns fluxos.
- **Headers/HTTPS:** a aplicação pública define CSP, `nosniff`, frame deny,
  referrer e HSTS em produção; o admin depende da borda e a configuração não é
  uniforme entre Caddy, nginx e URLs diretas.
- **Credenciais:** configuração aceita secrets em arquivos e falha fechada em
  produção, mas o pacote local contradiz esse desenho e os serviços não seguem
  menor privilégio.
- **LGPD:** há HMAC/minimização de documento, porém não há limitação de retenção
  integral, governança de backups/PDFs nem proteção suficiente da busca nominal.

## 9. Arquitetura e confiabilidade

### Transações, idempotência e saga

A transação por repositório está correta para cada operação no banco. A divisão
reserva→upload→finalização é necessária porque Drive e PostgreSQL não compartilham
transação. A compensação registra o ponteiro antes de excluir, o que é positivo.
Entretanto, o estado `failed` não possui transição de retry, a reserva ocorre fora
do `try`, e os jobs de reconciliação dependem de execução externa. O sistema precisa
de uma máquina de estados explícita, leases e tentativas para que retry seja uma
propriedade demonstrável.

### Concorrência

- Código e `business_key` usam constraints e passaram em testes de concorrência da
  saga.
- Template `max()+1` e ativação falharam no PostgreSQL efêmero.
- Rate limit e throttle são persistidos, portanto não são apenas memória, mas a
  identidade de IP é frágil por proxy.
- Não há teste de dois serviços/rollouts executando startup, seed, backfill e jobs
  simultaneamente.

### Armazenamento e memória

PDFs são gerados e baixados integralmente em memória. Um ZIP mantém N PDFs e o ZIP
simultaneamente. O limite de 200 itens não limita bytes. Drive usa download por
chunks para um `BytesIO`, mas o resultado final ainda é um único `bytes`. É
necessário medir tamanho real de PDF/template e definir orçamento de memória por
worker, não apenas número de itens.

### Migrations e rollout

As migrations são reversíveis em bancos descartáveis, mas downgrade não é garantia
de rollback seguro com dados reais. A criação de extensão/GIN requer privilégios e
pode falhar em serviço gerenciado. Alterações de schema e backfill no mesmo passo
não são adequadas para zero downtime. A migration 0005 também expõe dados de data
em warning, contrariando a política de logs.

### Backup, reconciliação e desastre

Existem bons runbooks iniciais e CLIs de integridade/reconciliação. Não há evidência
de agenda efetiva, backup cifrado fora do domínio de falha, restauração testada,
PITR configurado, failover exercitado ou responsabilidade institucional. Como o
banco é o mapa código→Drive, a perda do banco é um incidente crítico mesmo que os
PDFs permaneçam.

## 10. Frontend, experiência e acessibilidade

### Fluxos e estados

- **Login:** mostra loading e erro genérico e reage a sessão expirada; faltam
  recuperação/troca de senha e orientação de lockout.
- **Emissão:** upload→preview→geração é claro. O texto padrão contém evento,
  instituição, datas e placeholder de palestrante fixos
  (`EmitirCertificados.tsx:21-27`), criando risco acadêmico de emissão incorreta.
  Reset não limpa `dataEmissao` nem o input de arquivo (`:40-47`).
- **Preview:** limita listas a 50 sem informar quantas foram omitidas; a frase “este
  é exatamente o corpo” usa apenas a primeira linha, embora variáveis mudem por
  participante.
- **Geração:** spinner não representa progresso; não há cancelamento/retomada; o
  resumo omite falhas backend.
- **Histórico:** filtros, vazio, loading, seleção, ZIP e modal de revogação existem.
  O `useEffect` depende dos campos e dispara request a cada tecla, além do botão
  “Buscar” (`Historico.tsx:48-70`); faltam reemissão, detalhe de integridade e
  estados `pending`/`failed` explícitos.
- **Templates:** fluxo de versão/ativação existe, mas editor requer desktop e várias
  ações são hover-only.
- **Público:** estrutura é simples e responsiva, com labels e alerts. O principal
  problema de produto é privacidade/autorização, não estética.
- **Offline:** não há estado dedicado; erros de rede usam mensagens genéricas.

### Viewports — conclusão estática

| Viewport | Painel | Editor | Público | Comprovação |
|---|---|---|---|---|
| 320 px | padding e tablist sem wrap tendem a overflow | painéis fixos ocupam mais que a largura | formulários empilham abaixo de 480 px | inspeção estática; não validado em navegador |
| 768 px | telas principais usam grids responsivos | canvas fica estreito e topbar densa | grid de busca em duas colunas | inspeção estática |
| 1024 px | histórico/emissão utilizáveis com tabela rolável | utilizável, porém congestionado | adequado | inspeção estática |
| 1440 px | `max-w-6xl` mantém leitura | espaço suficiente | max-width de 56rem adequado | inspeção estática |

### WCAG 2.2 AA

Há labels, `role=alert/status`, tabela semântica e modal com foco. Permanecem tabs
incompletas, itens não acionáveis por teclado, controles hover-only, ausência de
foco global/reduced motion, contraste não medido e nenhuma suíte axe. Portanto,
**conformidade WCAG 2.2 AA não foi comprovada**.

## 11. Higiene do repositório e da entrega

### Estado Git

- `main` acompanha `origin/main`; nenhum arquivo rastreado estava modificado antes
  deste relatório.
- 154 caminhos são rastreados.
- 152 duplicatas `(2)` não rastreadas aparecem no status.
- 2.245 arquivos `(2)` existem em `.git`; `git fsck` falha, embora `HEAD^{commit}` e
  seus 330 objetos alcançáveis tenham sido lidos sem objeto ausente.
- O `HEAD` foi usado como fonte; as duplicatas não foram consideradas implementação.

### Gerados/locais observados, sem abrir conteúdo

| Categoria | Observação | Deve entrar em entrega/repositório público? |
|---|---|---|
| `node_modules` | presente; 16.842 caminhos ignorados no inventário inicial | Não |
| `dist` | 1 diretório de build do frontend | Não |
| caches Python/test/lint | 11 `__pycache__`, 2 `.pytest_cache`, 1 `.ruff_cache`, 138 `.pyc` | Não |
| `.tsbuildinfo` | 20 arquivos | Não |
| logs | 22 | Não |
| SQLite | 2 bancos + 2 WAL + 2 SHM | Não |
| planilhas locais | pelo menos 1 ignorada; 1 `participantes.xlsx` rastreada | Não, salvo fixture sintética mínima e documentada |
| PDFs | 17 ignorados, além do relatório técnico rastreado | PDFs gerados: não; relatório técnico: somente se necessário e revisado |
| `.env` | presente e ignorado; existe também cópia `(2)` | Não |
| credenciais | diretório `secrets/` e cópias `(2)` | Nunca |
| IDE/agentes | `.claude/settings.local.json`, `.agents`, `.codex`; somente `.claude/launch.json` é rastreado | Configuração local: não; launcher só se institucionalmente útil |
| fontes TTF | Arial/Times incluídas | Verificar licença de redistribuição antes de publicação |

### Ignore files

`.gitignore`, `.dockerignore` e `.gcloudignore` têm boa intenção e cobrem as
categorias principais. O problema é operacional: arquivos já rastreados ignoram
`.gitignore`, e padrões como `data/`/`*.xlsx` não impediram o XLSX aninhado de entrar
na imagem observada. Recomenda-se allowlist de build e teste automatizado do
contexto. Não há `.nvmrc`, `engines`, `.node-version` ou `.python-version`; Node 20 e
Python 3.12 aparecem apenas em Docker/CI.

### Conteúdo do ZIP

O ZIP local é estruturalmente íntegro (CRC, sem entrada criptografada ou traversal
detectado), mas é inadequado para entrega: 110.176.686 bytes, 23.352 entradas e
346.991.000 bytes descomprimidos. A razão máxima observada foi 59,03, sem indicação
de zip bomb pelos metadados; o risco é conteúdo indevido, não compressão maliciosa.

## 12. Testes executados

Todos os testes de aplicação abaixo usaram exportação limpa do `HEAD`; bancos e
arquivos ficaram em diretórios/containers descartáveis.

| Verificação/comando | Ambiente | Resultado | Observação |
|---|---|---|---|
| `git status`, `git log -5`, `git ls-files`, `git cat-file -e HEAD^{commit}`, `git diff --exit-code HEAD --` | repositório local | **Aprovado com ressalva** | `HEAD` íntegro e sem mudança rastreada; 152 duplicatas não rastreadas. |
| `git fsck --full --strict --no-reflogs` | repositório local | **Falhou (exit 10)** | milhares de arquivos `(2)` em `.git`, 4 refs ruins e objetos dangling; nenhum objeto alcançável do HEAD faltou. |
| extração de texto do PDF técnico | ferramenta local | **Aprovado** | 7 páginas/455 linhas; nenhum PDF de participante foi aberto. |
| inventário/CRC do ZIP por metadados | ferramenta local | **Aprovado estruturalmente / reprovado para entrega** | contagens da seção 11. |
| `python -m compileall -q ...` | Python 3.12.13 | **Aprovado** | backend, consulta, database, storage e observability. |
| `ruff check --no-cache .` | Ruff 0.16.2 / Python 3.12 | **Aprovado** | configuração atual só seleciona E9/F e mira py311. |
| instalação dos requirements + `pip check` | Python 3.12 limpo | **Aprovado** | instalação resolve; não garante reprodutibilidade futura. |
| `python -m pytest tests -p no:randomly -q` com manifests declarados | Python 3.12 limpo | **Falhou na coleta (exit 2)** | dependência `httpx2` ausente para o TestClient atual. |
| mesmo pytest após `httpx2` somente no ambiente descartável | Python 3.12 | **197 aprovados, 3 ignorados** | não transforma o manifesto do projeto em aprovado. |
| Alembic SQLite: upgrade head → check → downgrade base → upgrade head | SQLite descartável | **Aprovado** | sem drift no dialeto SQLite. |
| `test_integration_postgres.py` | PostgreSQL 16 efêmero | **3 aprovados** | testes usam schema local e não Drive real. |
| Alembic PostgreSQL: upgrade/downgrade/reupgrade | PostgreSQL 16 efêmero | **Aprovado** | sem banco real. |
| `alembic check` no PostgreSQL | PostgreSQL 16 efêmero | **Falhou** | drift do índice GIN criado pela migration 0004. |
| regressão local de retry `failed`/reemissão | SQLite descartável + storage fake | **Detectou falha** | retry vira duplicado `failed`; reemissão não muda status. |
| concorrência de templates | PostgreSQL 16 efêmero | **Detectou falha** | `IntegrityError` em criação e mais de um ativo. |
| `npm ci` | Node 20.20.2 / npm 10.8.2 | **Aprovado** | cópia limpa; lockfile consistente. |
| `npm run typecheck` | Node 20 | **Aprovado** | TypeScript sem erro. |
| `npm test -- --reporter=verbose` | Vitest/jsdom | **12 aprovados em 5 arquivos** | há warnings React `act(...)` em teste de App. |
| `npm run build` | Node 20 | **Aprovado** | chunks principais observados ~271 KB e Fabric ~280 KB, sem erro. |
| `docker compose config -q` dev/prod com valores sintéticos | Docker Compose local | **Aprovado** | nenhum secret real usado. |
| builds backend, web e web Cloud Run a partir do `HEAD` | Docker local | **Aprovado** | evidenciou XLSX/testes na imagem backend e nginx como usuário padrão. |

## 13. Testes que não puderam ser executados

| Teste/risco | Bloqueio exato | Ação recomendada |
|---|---|---|
| Google Drive real em staging | exigiria credencial/API externa, proibidas no escopo | staging isolado, identidades separadas, dados sintéticos e teste de permissão read-only |
| Cloud Run, Secret Manager, DNS, TLS e IAM atuais | estado externo não acessado | checklist institucional read-only e evidência exportada pelo responsável |
| Banco de produção/Neon e TLS efetivo | banco remoto proibido | staging PostgreSQL com CA/`verify-full`, teste de fail-closed |
| Branch protection/checks required | configuração do provedor Git não é arquivo local | responsável deve exportar regras e comprovar merge bloqueado |
| E2E em navegador nos 4 viewports | projeto não possui Playwright/Cypress nem browsers declarados; instalação externa não autorizada na fase final | adicionar harness versionado e executar local/CI |
| WCAG 2.2 AA, leitores de tela e contraste | sem axe/browser e sem teste manual assistivo | auditoria manual + automatizada nos fluxos completos |
| Performance/memória/carga | não há dataset sintético e orçamento/SLO aprovado | definir cenário e executar load test defensivo em staging |
| Interrupção real de worker/job | exigiria ambiente orquestrado e injeção de falha não prevista no escopo | testes de resiliência controlados em staging |
| Backup, restore, PITR, failover e rollback | não há backup sintético/runbook executável local completo; produção proibida | exercício periódico isolado com medição RPO/RTO |
| Reconciliação/integridade real do Drive | requer ler arquivos externos | staging sintético e relatório sem PII |
| Impressão/leitura de QR em dispositivos | não há matriz de dispositivos/impressoras | teste físico com PDFs sintéticos e QR pós-render |
| Scanner de imagem e advisories atualizados | dependem de ferramenta/base externa atual | executar em CI aprovado, com política de severidade bloqueante |
| Natureza do conteúdo da planilha/PDFs locais | conteúdo não foi aberto por restrição de privacidade | proprietário deve classificar fora deste relatório e remover da entrega até prova de sinteticidade |

## 14. Roadmap

### P0 — corrigir antes de compartilhar ou publicar

1. **RT-01/RT-02:** invalidar o ZIP, rotacionar credenciais por procedimento externo,
   reconstruir clone/entrega limpa e remover duplicatas/contaminação Git.
2. **RT-03:** desabilitar temporariamente download por nome ou implementar prova
   independente + token curto, único e server-side.
3. **RT-04:** retirar nomes de GET/URL/log/cache e minimizar resultados.
4. **RT-05:** separar credenciais/IAM do Drive; consulta somente leitura.
5. **RT-06:** restringir proxies confiáveis e testar rate limiting fim a fim.
6. Confirmar/remover `participantes.xlsx`, PDFs e fontes sem licença do material a
   compartilhar; usar apenas fixture sintética mínima.

### P1 — corrigir antes da apresentação

1. **RT-07:** lock Python/dev dependencies e fazer instalação limpa passar sem
   suplemento.
2. **RT-08/RT-09:** corrigir retry `failed` e concorrência de templates.
3. **RT-10:** alinhar contrato/preview/schema de planilha.
4. **RT-12/RT-13:** CI bloqueante com frontend tests e PostgreSQL/Alembic sem drift.
5. **RT-15/RT-16:** capabilities por papel, falhas visíveis, reemissão e roteiro de
   usuários/auditoria coerente.
6. **RT-24:** corrigir navegação por teclado e layout de apresentação; executar
   viewports e axe.
7. Trocar o texto padrão específico por modelo neutro e exigir revisão explícita.

### P2 — profissionalização

1. Jobs duráveis para geração, progresso, cancelamento e retry; ZIP/Drive em streaming.
2. Startup sem mutação, readiness completa e migrations expand/contract.
3. Hardening HTTP/docs/logs/TLS e containers mínimos não-root por digest.
4. Modelo de dados com FKs/tipos/checks completos.
5. Gestão de usuários, MFA, troca/reset de senha e UI de auditoria.
6. Observabilidade externa, scheduler com lock, backup/restore e RPO/RTO.
7. Política de retenção/LGPD cobrindo DB, PDF, Drive, logs e backups.
8. Refatoração em pacote Python, routers e casos de uso injetáveis.

### P3 — melhorias futuras

1. Editor mobile por drawers e atalhos de teclado documentados.
2. Dashboard de jobs, integridade, reconciliação e capacidade.
3. Testes de impressão/QR e perfis de template por finalidade, se aprovados pelo
   requisito acadêmico.
4. Internacionalização, preferências de acessibilidade e modo de baixa conectividade.
5. Relatórios de auditoria/exportação com anonimização e assinatura institucional.

## 15. Critérios objetivos para considerar o projeto pronto

### Pronto para apresentação acadêmica

- [ ] Novo pacote gerado de fonte limpa passa allowlist e não contém secrets, PII,
  `.git`, dependências, builds, caches, bancos, logs ou PDFs gerados.
- [ ] `git fsck --full --strict` passa e não há duplicatas `(2)`.
- [ ] Nenhuma credencial do pacote antigo permanece válida.
- [ ] Busca nominal está desabilitada ou exige confirmação independente comprovada;
  nenhum nome aparece em URL/log/cache.
- [ ] Setup limpo Python 3.12 e Node 20 executa compile, Ruff, migrations, backend,
  typecheck, frontend tests e build sem passo manual oculto.
- [ ] Todos os testes de correção P0/P1 passam e CI os executa de modo bloqueante.
- [ ] Roteiro usa somente dados sintéticos e texto/template revisados.
- [ ] Admin, secretaria e auditor veem somente capabilities coerentes; falhas do lote
  ficam visíveis.
- [ ] Fluxo sintético completo passa: login→preview→emissão→QR→consulta→download→
  revogação→bloqueio→reemissão.
- [ ] Teclado e viewports 320/768/1024/1440 passam sem bloqueio funcional; achados
  axe críticos/sérios são zero.

### Pronto para produção

Além de todos os critérios de apresentação:

- [ ] Consulta usa identidade Drive read-only distinta; admin, jobs e banco seguem
  menor privilégio; evidência de IAM revisada por duas pessoas.
- [ ] Proxy/IP/rate limit passam testes na topologia real e têm alerta de abuso.
- [ ] PostgreSQL exige TLS verificável, schema está sem drift e rollout é
  expand/contract sem lock incompatível com o SLO.
- [ ] Retry, concorrência de template, interrupção de worker e múltiplas instâncias
  convergem sem duplicação/perda.
- [ ] Geração/ZIP têm limites de memória/bytes, jobs duráveis, progresso e retomada.
- [ ] Docs de API estão restritas; headers são uniformes; logs e auditoria não
  contêm PII/segredos/localizadores desnecessários.
- [ ] Política institucional de senha/MFA/recuperação, gestão de usuários e revisão
  periódica de acessos está operacional.
- [ ] Política LGPD define finalidade, base legal, retenção, descarte, titulares,
  responsáveis e incidentes em DB/Drive/logs/backups.
- [ ] Backup cifrado, restore, reconciliação, PITR, failover e rollback foram
  exercitados; RPO/RTO medidos e aceitos.
- [ ] E2E, contratos, acessibilidade, segurança defensiva, carga, migrations e
  staging Drive são checks bloqueantes.
- [ ] Métricas/logs/traces são consolidados entre workers e alertas têm runbook/on-call.
- [ ] Imagens/ações/dependências são fixadas, escaneadas por política e atualizadas
  por processo controlado.

## Encerramento — resumo para terminal

### Dez problemas mais importantes

1. ZIP/working tree com secrets e artefatos de dados.
2. Busca nominal devolve o autorizador do próprio download.
3. Nome em GET/URL e resposta nominal enumerável, sem `no-store` adequado.
4. Consulta pública compartilha credencial Drive com escrita.
5. Uvicorn confia em forwarded headers de qualquer origem.
6. Emissão `failed` bloqueia retry e reemissão não corrige estado.
7. Templates falham e podem ficar múltiplos ativos sob concorrência.
8. Backend limpo não coleta testes por dependência ausente.
9. Geração/ZIP síncronos e integralmente em memória.
10. Frontend/CI não refletem papéis, falhas, PostgreSQL e testes necessários.

### Bloqueadores para apresentação

- saneamento/rotação e nova entrega limpa;
- Git íntegro sem duplicatas;
- busca nominal corrigida ou desabilitada;
- instalação backend reproduzível;
- dados/texto/template exclusivamente sintéticos e revisados;
- fluxos por papel e falhas do lote coerentes;
- teclado e viewports essenciais validados.

### Bloqueadores adicionais para produção

- credenciais Drive separadas e menor privilégio;
- proxy/rate limit correto;
- retry/concorrência/jobs duráveis;
- migration PostgreSQL sem drift e rollout seguro;
- TLS/headers/docs/logs endurecidos;
- retenção LGPD, backup/restore/failover comprovados;
- observabilidade multi-worker e CI/E2E/staging bloqueantes.

### Arquivo criado

- `docs/REVISAO_TECNICA_ATUAL.md` — único arquivo criado pela revisão.

### Comandos de validação relevantes

```text
git status --porcelain=v2 --branch
git log -5 --oneline --decorate
git ls-files
git cat-file -e HEAD^{commit}
git diff --exit-code HEAD --
git fsck --full --strict --no-reflogs
git archive HEAD
rg / find / nl / wc / sha256sum / cmp (inventário e evidências locais)
python -m compileall -q certificados-admin/backEnd certificados-consulta database storage_service observability
ruff check --no-cache .
python -m alembic upgrade head
python -m alembic check
python -m alembic downgrade base
python -m pytest tests -p no:randomly -q
npm ci
npm run typecheck
npm test -- --reporter=verbose
npm run build
docker compose config -q
docker build (backend, web e cloudrun-web em contexto descartável)
```

### Resultado consolidado

- **Aprovados:** HEAD alcançável; compile; Ruff; SQLite migrations/check;
  PostgreSQL integration e ciclo de migrations; backend 197/3 após suplemento
  temporário; frontend `npm ci`, typecheck, 12 testes e build; Compose; builds Docker;
  CRC do ZIP.
- **Falharam:** `git fsck`; pytest com dependências declaradas; `alembic check` no
  PostgreSQL; regressões de retry `failed` e concorrência de templates; adequação do
  ZIP para entrega.
- **Sem comprovação:** sistemas externos, Drive/IAM real, Cloud Run, banco/TLS real,
  branch protection, E2E nos quatro viewports, WCAG AA, carga/memória, backup/restore,
  failover, rollback, staging Drive, impressão/QR físico e natureza dos dados locais.
