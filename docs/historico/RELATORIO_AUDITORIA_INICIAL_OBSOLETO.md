# Relatório de Auditoria Técnica — CertificadosSecretaria

> Auditoria de código (sem alterações no sistema). Data: 2026-06-19.
> Escopo: `certificados-admin/backEnd`, `certificados-admin/frontend`,
> `certificados-consulta`, `database`, `storage_service`.
> Metodologia: o código foi tratado como fonte de verdade; o README e os
> comentários foram confrontados com o comportamento real. Todas as conclusões
> apontam arquivo:linha. Verificações dinâmicas foram feitas em banco/diretório
> temporário, sem tocar nos dados reais.

---

## 1. Resumo executivo

O projeto está **funcional e bem organizado para um piloto de desenvolvimento**:
a suíte de 77 testes passa, o build do frontend compila, há separação clara
entre admin e consulta, camada de storage plugável (local/Drive), autenticação
JWT+bcrypt, trilha de auditoria e um fluxo estruturado de planilha →
validação → preview → geração com idempotência por `business_key`.

Entretanto, **não está pronto para produção**. Foram encontrados defeitos que
comprometem garantias centrais do domínio (validação e integridade de
certificados):

- A **validação por QR Code está quebrada**: o QR aponta para
  `…/validar/{code}`, rota que **não existe** na aplicação pública (existe
  `/public/verify/{code}`). Um QR impresso hoje leva a um 404.
- A **geração não é transacional**: os PDFs são enviados ao storage antes de
  qualquer escrita no banco e a persistência usa `INSERT OR IGNORE`. Em colisão
  de chave ou falha parcial, a API responde "gerado" enquanto **nenhum registro
  é salvo** — certificado perdido e arquivo órfão.
- A **alocação de código e a checagem de `business_key` não são transacionais**,
  permitindo perda silenciosa de certificados sob concorrência.
- **Reemissão** sempre usa o template padrão e **não guarda snapshot** do
  template original; no Google Drive ainda deixa o arquivo antigo **órfão**.
- A **busca pública por nome revela o código**, que por si só **autoriza o
  download** do PDF com dados pessoais — risco de enumeração e LGPD.
- **Datas são armazenadas por extenso** e usadas na ordenação, produzindo ordem
  cronológica incorreta (confirmado empiricamente).
- **Login sem proteção contra força bruta**; em produção, **a aplicação não
  falha ao subir sem `JWT_SECRET`** (usa segredo efêmero).

A arquitetura "dois deploys independentes" também é, hoje, **inconsistente**:
ambos dependem do **mesmo arquivo SQLite e do mesmo filesystem local**, o que só
funciona em uma única máquina com volume compartilhado.

**Conclusão:** ótimo como base; requer uma rodada de correções de
consistência/segurança antes de homologação e produção. A lista priorizada está
na seção 13 e no fim do documento.

---

## 2. Veredito sobre prontidão

| Ambiente | Veredito | Justificativa resumida |
|---|---|---|
| **Desenvolvimento** | ✅ Apto | Testes passam, build compila, fluxo principal funciona com storage local. |
| **Homologação** | ⚠️ Apto com ressalvas | Só após corrigir QR `/validar`, transacionalidade da geração, ordenação de datas e expor `JWT_SECRET`/admin atrás de rede. Caso contrário, a homologação valida um comportamento que mudará. |
| **Produção** | ❌ Não apto | Defeitos críticos de integridade (geração não-transacional, perda silenciosa sob concorrência), validação por QR quebrada, ausência de proteção a força bruta, segredo JWT efêmero, LGPD/enumeração na consulta, e arquitetura de storage incompatível com deploys independentes. |

---

## 3. Arquitetura atual

### 3.1 Componentes

- **certificados-admin/backEnd** (FastAPI, porta 8000) — [main.py](certificados-admin/backEnd/main.py).
  Autenticação ([auth.py](certificados-admin/backEnd/auth.py)), geração de PDF
  ([services/generator.py](certificados-admin/backEnd/services/generator.py)),
  orquestração de lote
  ([services/certificate_service.py](certificados-admin/backEnd/services/certificate_service.py)),
  validação de planilha
  ([services/spreadsheet.py](certificados-admin/backEnd/services/spreadsheet.py)),
  templates por curso
  ([utils/template_store.py](certificados-admin/backEnd/utils/template_store.py))
  e templates visuais
  ([services/visual_template_store.py](certificados-admin/backEnd/services/visual_template_store.py),
  [routers/visual_templates.py](certificados-admin/backEnd/routers/visual_templates.py)).
- **certificados-admin/frontend** (React 19 + TS + Vite 8 + Tailwind 4 + Fabric.js 5) —
  [src/App.tsx](certificados-admin/frontend/src/App.tsx) com abas Emitir /
  Histórico / Validar / Editor visual / Templates.
- **certificados-consulta** (FastAPI + Jinja2, porta 8001) —
  [app.py](certificados-consulta/app.py), site público sem login.
- **database** (SQLite compartilhado) — [db.py](database/db.py),
  [schema.sql](database/schema.sql).
- **storage_service** (local/Google Drive) —
  [__init__.py](storage_service/__init__.py),
  [local.py](storage_service/local.py),
  [google_drive.py](storage_service/google_drive.py),
  [config.py](storage_service/config.py).

### 3.2 Fluxo Excel → … → download (modelo estruturado, usado pela UI)

1. **Upload + validação** — `POST /certificates/validate-spreadsheet`
   ([main.py:532](certificados-admin/backEnd/main.py)) lê e valida a planilha
   ([spreadsheet.read_and_validate](certificados-admin/backEnd/services/spreadsheet.py));
   retorna preview (nada é persistido).
2. **Geração confirmada** — `POST /certificates/generate`
   ([main.py:553](certificados-admin/backEnd/main.py)) →
   `CertificateBatchService.generate_certificates`
   ([certificate_service.py:185](certificados-admin/backEnd/services/certificate_service.py)):
   calcula `business_key`, pula duplicatas, aloca códigos
   ([certificate_store.allocate_codes](certificados-admin/backEnd/services/certificate_store.py)),
   renderiza PDF em memória (default ou template visual), monta o QR
   `…/validar/{code}`, envia ao storage e **só depois** grava metadados via
   `save_certificates` → `db.insert_certificates` (`INSERT OR IGNORE`).
3. **Storage** — `LocalStorage.save` grava em `storage/pdfs` ou
   `GoogleDriveStorage.save` envia ao Drive; retorna metadados
   (`checksum_sha256`, `file_size`, `drive_file_id`, …).
4. **Banco** — uma linha por certificado em `certificates`.
5. **Pesquisa/Download** — admin: `GET /certificates` (filtros) e
   `GET /certificate-file/{code}` (autenticado); consulta:
   `/public/search`, `/public/verify/{code}`,
   `/public/certificates/{code}/download`.

> Existe também um **fluxo legado** `POST /generate-certificates`
> ([main.py:457](certificados-admin/backEnd/main.py) →
> `generate_from_excel` [certificate_service.py:94](certificados-admin/backEnd/services/certificate_service.py))
> com semântica diferente (ver F14). A UI **não** o utiliza.

### 3.3 Autenticação

- `POST /auth/login` valida via bcrypt
  ([auth.authenticate](certificados-admin/backEnd/auth.py)), emite JWT HS256 e o
  entrega em **cookie HttpOnly** (`SameSite=Lax`) e no corpo
  ([main.py:257](certificados-admin/backEnd/main.py)).
- `get_current_admin` aceita cookie **ou** `Authorization: Bearer`
  ([auth.py:122](certificados-admin/backEnd/auth.py)).
- Segredo do JWT vem de `JWT_SECRET`; **sem ele, gera segredo efêmero por
  processo** ([auth.py:39](certificados-admin/backEnd/auth.py)).

### 3.4 Integração admin ↔ consulta

Acoplamento por **dados compartilhados**: mesmo `certificates.db` e mesma pasta
`storage/pdfs`, resolvidos em [db.py:61-67](database/db.py). A consulta importa
`database.db` e `storage_service` diretamente.

### 3.5 Estratégia de templates (três coexistindo)

1. **Template padrão global** `templates/certificado_base.png`
   ([main.py:73](certificados-admin/backEnd/main.py)).
2. **Template por curso** (PNG/JPG) em `APPDATA/CertificadosApp/templates`
   ([template_store.register_template](certificados-admin/backEnd/utils/template_store.py)),
   resolvido por `get_template_for_course`.
3. **Templates visuais** (layout estilo editor) em `visual_templates.json`
   ([visual_template_store.py](certificados-admin/backEnd/services/visual_template_store.py)),
   selecionáveis por lote.

### 3.6 Deploy

README sugere **um servidor** com os dois backends sobre o mesmo SQLite
([README.md:398](README.md)). Não há Dockerfile, CI, nem scripts de
backup/migração. Storage de produção previsto: Google Drive (Service Account).

---

## 4. Matriz requisitos × implementação

### 4.1 Área administrativa

| Requisito | Situação | Evidência / observação |
|---|---|---|
| Autenticação obrigatória | ✅ Implementado | JWT+bcrypt; rotas protegidas por `Depends(get_current_admin)`. Ressalvas: sem anti-bruteforce (F4), sem revogação de sessão (F13). |
| Upload de planilha Excel | ✅ Implementado | `read_spreadsheet_upload` valida `.xlsx`, magic `PK`, tamanho ([main.py:181](certificados-admin/backEnd/main.py)). |
| Validação e pré-visualização | ✅ Implementado | `validate-spreadsheet` + preview na UI ([EmitirCertificados.tsx](certificados-admin/frontend/src/pages/EmitirCertificados.tsx)). |
| Template padrão único para todos | ⚠️ Incompatível | Há **3 estratégias** (padrão + por curso + visual). Diverge de "um template padrão global" (F-doc, ver seção 11). |
| Geração de PDF | ✅ Implementado | PIL compõe imagem → PDF A4 300dpi ([generator.py](certificados-admin/backEnd/services/generator.py)). |
| Código verificador único | ⚠️ Parcial | Formato `CERT-ANO-XXXXXX` + índice UNIQUE, mas alocação/persistência não-transacional (F1/F2). |
| Pesquisa por nome (todos da pessoa) | ⚠️ Parcial | Funciona, mas curingas `%`/`_`, sem acento-insensibilidade e sem índice útil (F10). |
| Pesquisa por código exato | ✅ Implementado | `get_by_code` com `COLLATE NOCASE` ([db.py:242](database/db.py)). |
| Download individual | ✅ Implementado | `/certificate-file/{code}` + UI Histórico. |
| Download em lote | ⚠️ Parcial | Backend tem `/certificates/download-zip` e `/download-certificates`, mas **não há UI** no frontend (F22). |
| Histórico | ✅ Implementado | `GET /certificates` + página Histórico. |
| Revogação | ✅ Implementado | `/certificates/{code}/revoke` + auditoria. |
| Reemissão | ⚠️ Incompatível | Não reusa template original; sempre layout padrão; cria órfãos no Drive (F6). |
| Auditoria | ⚠️ Parcial | `audit_log` registra ações, mas sem FK/constraints e sem hash/IP (F16). |

### 4.2 Área pública

| Requisito | Situação | Evidência / observação |
|---|---|---|
| Pesquisa por nome ou código | ✅ Implementado | `/`, `/public/search`, `/public/verify` ([app.py](certificados-consulta/app.py)). |
| Visualização do estado | ✅ Implementado | `status`/`revoked` em `/public/verify` e selo na página. |
| Download do PDF | ✅ Implementado | `/public/certificates/{code}/download` (bloqueia revogado → 410). |
| Validação de código/QR | ❌ Ausente/Incompatível | QR aponta para `/validar/{code}` **inexistente** (F3). |
| Não expor dados administrativos/pessoais | ⚠️ Parcial | `_public_view` oculta e-mail/documento, mas o código exposto autoriza download (F7 — LGPD/enumeração). |
| Implantação separada | ⚠️ Incompatível | Depende de SQLite + filesystem compartilhados (F18). |

---

## 5. Achados priorizados

> Severidade: **Crítica / Alta / Média / Baixa**. Confiança: **Alta** (confirmado
> no código/execução), **Média** (forte indício), **Baixa** (depende de contexto).

| ID | Sev. | Conf. | Categoria | Descrição (resumo) | Evidência (arquivo:linha) | Impacto | Reproduzir | Correção recomendada | Esforço |
|---|---|---|---|---|---|---|---|---|---|
| **F1** | Crítica | Alta | Consistência/Transação | Geração não-transacional: PDFs são enviados ao storage **antes** da escrita no banco e a persistência é `INSERT OR IGNORE`. Falha parcial ou colisão de chave → API responde "gerado" sem linha no banco; PDF fica órfão. | [certificate_service.py:219-262](certificados-admin/backEnd/services/certificate_service.py); `INSERT OR IGNORE` em [db.py:221-237](database/db.py) | Perda silenciosa de certificados; PDFs órfãos; relatório de sucesso falso. | Enviar lote com uma `business_key` já existente: a linha é ignorada mas o storage recebe o arquivo e a resposta lista como "generated". | Persistir metadados na **mesma transação**; trocar `INSERT OR IGNORE` por inserção que detecta conflito e reporta; só confirmar storage após `commit` (ou compensar/rollback do upload). | Alto |
| **F2** | Crítica | Alta | Concorrência | `allocate_codes` lê `existing_codes()` e gera códigos fora de transação; checagem de `business_key` (`get_by_business_key`) também. Duas requisições concorrentes podem gerar o mesmo código/`business_key`; `INSERT OR IGNORE` descarta um deles silenciosamente após o PDF já ter sido salvo. | [certificate_store.py:37-51](certificados-admin/backEnd/services/certificate_store.py); [certificate_service.py:205-262](certificados-admin/backEnd/services/certificate_service.py) | Perda de certificado sob carga; inconsistência código↔arquivo. | Disparar duas gerações simultâneas do mesmo lote. | Alocar código com `INSERT` atômico (retry no `UNIQUE`), ou reservar dentro de transação `IMMEDIATE`; tratar `IntegrityError` explicitamente. | Alto |
| **F3** | Alta | Alta | Regra de negócio/Validação | O QR aponta para `PUBLIC_VALIDATION_BASE_URL/validar/{code}`, mas a consulta só expõe `/public/verify/{code}` — `/validar/{code}` **não existe**. | QR: [certificate_service.py:221](certificados-admin/backEnd/services/certificate_service.py) e [:294](certificados-admin/backEnd/services/certificate_service.py); rotas reais: [app.py:160,198,203](certificados-consulta/app.py); doc: [README.md:180](README.md), [.env.example:17](.env.example) | QR impresso leva a 404; validação anti-fraude inutilizada. | `import app; [r.path for r in app.app.routes]` → sem `/validar`. | Criar rota `/validar/{code}` (página HTML de validação) **ou** ajustar o QR para a rota existente. Adicionar teste de contrato QR↔rota. | Médio |
| **F4** | Alta | Alta | Segurança (OWASP A07) | `POST /auth/login` sem rate limit nem bloqueio progressivo; `authenticate` apenas compara bcrypt. | [main.py:257-291](certificados-admin/backEnd/main.py); [auth.py:152-159](certificados-admin/backEnd/auth.py) | Força bruta/credential stuffing viável. | Repetir logins inválidos: sem 429/lockout. | Rate limit por IP+usuário, atraso/lockout, log de falhas; CAPTCHA opcional. | Médio |
| **F5** | Alta | Alta | Config/Deploy | Sem `JWT_SECRET`, a app gera **segredo efêmero por processo** e apenas loga aviso — não falha em produção. | [auth.py:39-52](certificados-admin/backEnd/auth.py) | Tokens invalidados a cada restart/worker; risco de segredo fraco em prod. | Subir sem `JWT_SECRET`: app inicia normalmente. | Exigir `JWT_SECRET` quando `APP_ENV=production` (abortar start); validar comprimento mínimo. | Baixo |
| **F6** | Alta | Alta | Reemissão/Storage | Reemissão sempre renderiza com **template padrão** (ignora visual e o curso), **não guarda snapshot/versão** do template original e, no Drive, cria novo `file_id` deixando o anterior **órfão**. | [certificate_service.py:267-302](certificados-admin/backEnd/services/certificate_service.py); Drive cria sem apagar antigo [google_drive.py:77-125](storage_service/google_drive.py); update em [db.py:428-461](database/db.py) | Certificado reemitido diverge do original; arquivos órfãos no Drive; impossível auditar versão. | Reemitir um certificado gerado com template visual → sai com layout padrão. | Persistir referência/snapshot do template usado; reusar na reemissão; apagar (ou versionar) o arquivo antigo no Drive. | Alto |
| **F7** | Alta | Média | LGPD/Privacidade | A busca pública por nome retorna o `unique_code`, e o download exige **apenas** o código → enumeração de certificados de terceiros e acesso ao PDF com dados pessoais. | `_public_view` expõe código [app.py:46-56](certificados-consulta/app.py); download por código [app.py:198-206](certificados-consulta/app.py) | Exposição de dados pessoais; correlação nome→certificado→PDF por qualquer pessoa. | Buscar um nome comum → copiar código → baixar PDF sem autenticação. | Avaliar download sob verificação adicional (ex.: documento/data nasc.), marca d'água, ou expor download só na validação por código direto; revisar base legal LGPD e minimização. | Médio |
| **F8** | Alta | Alta | Banco/Datas | `issue_date` é armazenada **por extenso** e usada para ordenar (`ORDER BY issue_date`). Ordenação vira alfabética, não cronológica. **Confirmado empiricamente.** | escrita por extenso [dates.py:28-31](certificados-admin/backEnd/utils/dates.py); ordenação [db.py:351-364](database/db.py); usado em [app.py:131-136](certificados-consulta/app.py) | Histórico e busca pública em ordem errada; paginação enganosa. | Inserir datas dez/2025, jan/2026, abr/2026 e ordenar DESC → retorna jan, dez, abr. | Guardar data ISO (`YYYY-MM-DD`) em coluna própria para ordenação/índice; manter "por extenso" só para exibição. | Médio |
| **F9** | Média | Alta | Regra de negócio | Em template visual, o campo rotulado "Evento/Curso" (`event`) recebe o **curso**, não o evento — `_row_to_record` descarta `row.evento`. | mapeamento [generator.py:391-398](certificados-admin/backEnd/services/generator.py); record sem evento [certificate_service.py:360-373](certificados-admin/backEnd/services/certificate_service.py); label [types/template.ts:14-23](certificados-admin/frontend/src/types/template.ts) | Certificado visual imprime o curso onde deveria constar o evento. | Gerar via template visual com `event` no layout → mostra o curso. | Propagar `evento` ao `ParticipantRegistryRecord`/`participant_data["event"]`; separar chaves `course` e `event`. | Baixo |
| **F10** | Média | Alta | Busca/SQL | Busca por nome usa `LIKE %termo%`: `%`/`_` viram **curingas**, não usa índice, e `COLLATE NOCASE` **não** é insensível a acentos; termos curtos/`%` listam grande volume. **Confirmado empiricamente.** | [db.py:334-335](database/db.py), [search_by_name:258-275](database/db.py) | Vazamento por enumeração ampla; performance ruim; busca não encontra "José" ao digitar "jose". | `name="%"` retorna tudo; `name="_na"` casa "Ana". | Escapar `%`/`_` (ESCAPE) ou usar igualdade por token; normalizar acentos (coluna `name_normalized`) + índice; exigir tamanho mínimo do termo. | Médio |
| **F11** | Média | Alta | Rate limit/Proxy | `rate_limit` não cobre a página HTML `/` nem a rota legada `/certificado/{code}/download`; é por-processo (`dict` em memória) e usa `request.client.host` (IP do proxy atrás de nginx; cada worker tem seu balde). | dependência ausente em [app.py:103-154](certificados-consulta/app.py) e [app.py:203-206](certificados-consulta/app.py); balde [app.py:61-76](certificados-consulta/app.py) | Limite ineficaz atrás de proxy/múltiplos workers; rotas mais sensíveis sem limite. | Baixar pela rota legada repetidamente: sem 429. | Aplicar limite em todas as rotas públicas; usar store compartilhado (Redis) e `X-Forwarded-For` confiável; limitar na borda (nginx). | Médio |
| **F12** | Média | Alta | Integridade | `checksum_sha256` é gravado mas **nunca verificado** no download (admin e público). | grava em [base.py:84-85](storage_service/base.py); download sem verificação [__init__.py:72-91](storage_service/__init__.py) | Corrupção/adulteração no storage não é detectada ao servir. | Alterar bytes do PDF no storage → download segue servindo. | Recalcular e comparar checksum no download (ao menos no Drive); logar/recusar divergência. | Baixo |
| **F13** | Média | Alta | Sessão/AuthZ | JWT stateless: `logout` só apaga o cookie; o token continua válido até `exp`. Sem revogação/rotação; sem `jti`/denylist. | logout [main.py:293-297](certificados-admin/backEnd/main.py); decode [auth.py:112-146](certificados-admin/backEnd/auth.py) | Token vazado/roubado não pode ser invalidado; logout não encerra a sessão de fato. | Logar, copiar token, usar após logout → ainda autentica. | TTL curto + refresh; denylist por `jti`; invalidar por `password_changed_at`/versão de sessão. | Médio |
| **F14** | Média | Alta | Duplicação/Consistência | Fluxo legado `/generate-certificates` grava `event_name = curso`, **exige e-mail**, não calcula `business_key` (sem idempotência), sem dados estruturados (quebra reemissão). Coexiste com o estruturado. | rota [main.py:457-528](certificados-admin/backEnd/main.py); `"event": record.curso` [certificate_service.py:163](certificados-admin/backEnd/services/certificate_service.py); e-mail obrigatório [reader.py:16,43-48](certificados-admin/backEnd/services/reader.py) | Dados inconsistentes se a rota for usada; manutenção dobrada; confusão evento/curso. | Chamar `/generate-certificates`: gera certificados sem `business_key` e com curso no `event_name`. | Remover/depreciar o fluxo legado ou alinhá-lo ao estruturado; documentar. | Médio |
| **F15** | Média | Média | Upload/DoS | Imagens de template (background e **data URLs** em elementos) são abertas no PIL **sem limite de pixels** (decompression bomb); a planilha é parseada inteira **antes** de checar `max_rows`. | background [visual_template_store.py:99-112](certificados-admin/backEnd/services/visual_template_store.py); data URL sem limite [generator.py:495-514](certificados-admin/backEnd/services/generator.py); parse antes do limite [spreadsheet.py:185-205](certificados-admin/backEnd/services/spreadsheet.py) | Consumo excessivo de CPU/memória; possível DoS por admin comprometido/erro. | Subir PNG "bomba" 10MB que descomprime para centenas de Mpx. | Definir `Image.MAX_IMAGE_PIXELS` e validar dimensões; limitar tamanho de data URL; ler planilha com limite de linhas/streaming. | Médio |
| **F16** | Média | Alta | Banco/Constraints | Sem `CHECK` em `status`/`role`/`storage_provider`; sem **FOREIGN KEY** para `issued_by`, `revoked_by`, `audit_log.actor_id` → integridade referencial frágil (apesar de `PRAGMA foreign_keys=ON`). | [schema.sql:28,47,20](database/schema.sql); colunas em [db.py:97-120](database/db.py) | Estados inválidos persistíveis; auditoria sem vínculo garantido ao usuário. | `UPDATE` com `status='qualquer'` é aceito. | Adicionar `CHECK(status IN(...))`, `CHECK(role IN(...))`, FKs; migração cuidadosa. | Médio |
| **F17** | Média | Alta | Frontend/Performance | Bundle único de **593 KB** (gzip 177 KB) acima do limite de 500 KB; Fabric.js é importado **eagerly** (editor carregado mesmo sem abrir a aba). | build: `dist/assets/index-*.js 593.12 kB`; import estático [App.tsx:7](certificados-admin/frontend/src/App.tsx); sem `manualChunks` [vite.config.ts](certificados-admin/frontend/vite.config.ts) | Carregamento inicial lento. | `npm run build` → aviso de chunk >500KB. | `React.lazy`/`import()` para a aba do editor; `manualChunks` separando Fabric.js. | Baixo |
| **F18** | Média | Alta | Arquitetura/Deploy | "Dois deploys independentes" dependem do **mesmo SQLite e mesmo filesystem**; sem volume compartilhado não há independência. Sem backup/migração/recuperação formais. | paths compartilhados [db.py:61-91](database/db.py); local storage [local.py](storage_service/local.py); README [README.md:398-409](README.md) | Impede escalar/isolar; SQLite WAL não atravessa rede; risco de perda sem backup. | Implantar admin e consulta em hosts distintos sem disco compartilhado → consulta não acha os dados. | Banco gerenciado (Postgres) + storage de objetos (Drive/S3); ou manter monólito único e documentar; rotina de backup/restore. | Alto |
| **F19** | Média | Alta | Dependências | `npm audit` reporta **8 vulnerabilidades (6 high)**, incl. `ws` (divulgação de memória / DoS). | `npm audit --omit=dev` (transitivas de build/dev) | Superfície de risco na toolchain. | `npm audit`. | `npm audit fix`; fixar versões; revisar no CI. | Baixo |
| **F20** | Baixa | Alta | AuthZ/Exposição | A rota `/validate/{code}` no backend **admin** é **pública** (sem `Depends`) e retorna `certificate_text`/`event`. | [main.py:316-333](certificados-admin/backEnd/main.py) | Vazamento de texto do certificado se o admin ficar acessível. | `GET /validate/<code>` sem token → 200 com dados. | Proteger a rota ou removê-la (a validação pública é responsabilidade da consulta). | Baixo |
| **F21** | Baixa | Média | Path traversal (defesa) | Download local aceita `pdf_path` **absoluto** sem rejeitar `..`; `resolve_pdf_path` retorna absoluto inalterado. `pdf_path` é gerado pelo sistema (risco baixo), mas sem defesa em profundidade. | [local.py:74-83](storage_service/local.py); [db.py:278-284](database/db.py) | Leitura de arquivo fora do storage se `pdf_path` for adulterado. | Forjar linha com `pdf_path` absoluto apontando fora do storage. | Normalizar e confinar a `STORAGE_DIR` (`resolve()`+`is_relative_to`); rejeitar absolutos/`..`. | Baixo |
| **F22** | Baixa | Alta | Requisito/UX | "Download em lote" existe no backend (`/certificates/download-zip`, `/download-certificates`) mas **não há UI** no frontend (Histórico só baixa individual). | backend [main.py:704-797](certificados-admin/backEnd/main.py); UI sem seleção em lote [Historico.tsx:179-200](certificados-admin/frontend/src/pages/Historico.tsx) | Requisito central só meio-atendido. | Abrir Histórico: não há seleção múltipla/ZIP. | Adicionar seleção e botão "Baixar selecionados (ZIP)". | Médio |
| **F23** | Baixa | Alta | Dados/LGPD (higiene) | O diretório contém **arquivos com dados reais** (planilha de participantes e PDFs nomeados com pessoas); `data/participantes.xlsx` **não** está no `.gitignore` (só os PDFs de `output` e `storage`). | [.gitignore](.gitignore) ignora `storage/pdfs/*.pdf` e `output/.../*.pdf`, mas não `certificados-admin/backEnd/data/` | Risco de vazamento de dados pessoais se um repositório for inicializado. | Inicializar git e `git add .` incluiria a planilha real. | Mover dados de teste para fora do repo/anonimizar; adicionar `data/` ao `.gitignore`; usar fixtures sintéticas. | Baixo |
| **F24** | Baixa | Média | CSRF/Sessão | Endpoints mutáveis aceitam cookie de sessão. `SameSite=Lax` mitiga CSRF em POST cross-site, mas não há token anti-CSRF e a aceitação de `Bearer` amplia a superfície; falta verificação explícita em produção. | cookie `samesite="lax"` [main.py:282-290](certificados-admin/backEnd/main.py) | Risco residual de CSRF em cenários específicos. | Revisar com `Origin`/`SameSite` desabilitado. | Manter `SameSite=Lax/Strict`, validar `Origin`/`Referer` em mutações, ou token CSRF. | Baixo |
| **F25** | Baixa | Alta | UX/Acessibilidade | Revogação usa `window.prompt`/`alert`; sem confirmação acessível/foco; mensagens de erro genéricas; sem estados de carregamento em algumas ações. | [Historico.tsx:55-66](certificados-admin/frontend/src/pages/Historico.tsx) | UX/acessibilidade aquém para uso administrativo. | Revogar um certificado → diálogo nativo. | Modal acessível com motivo obrigatório/validado; feedback de sucesso/erro. | Baixo |

---

## 6. Defeitos confirmados (reproduzíveis)

1. **QR para rota inexistente (F3)** — inspeção das rotas da consulta em runtime
   confirma que só há `/public/verify`, `/public/search`,
   `/public/certificates/{code}/download` e `/certificado/{unique_code}/download`;
   **não há `/validar/{code}`**, exatamente o caminho gravado no QR
   ([certificate_service.py:221](certificados-admin/backEnd/services/certificate_service.py))
   e documentado ([README.md:180](README.md)).
2. **Ordenação cronológica incorreta (F8)** — em banco temporário, inserindo
   `5 de dezembro de 2025`, `5 de janeiro de 2026`, `5 de abril de 2026` e
   ordenando por `issue_date` DESC, o resultado foi **janeiro → dezembro →
   abril** (ordem alfabética).
3. **Curingas na busca (F10)** — `name="%"` retornou **todos** os registros;
   `name="_na"` casou "Ana Souza"/"Ana Lima" (o `_` agiu como curinga).
4. **Confusão evento/curso em template visual (F9)** —
   `participant_data["event"] = participant.curso`
   ([generator.py:393](certificados-admin/backEnd/services/generator.py)) e o
   record nunca recebe `evento`.
5. **Geração não-transacional / `INSERT OR IGNORE` (F1)** — storage é gravado no
   laço ([certificate_service.py:238](certificados-admin/backEnd/services/certificate_service.py))
   e o banco só depois, com `INSERT OR IGNORE`
   ([db.py:232](database/db.py)).
6. **Segredo JWT efêmero (F5)** — confirmado por leitura e pelo aviso de teste
   `InsecureKeyLengthWarning` na suíte.
7. **Bundle 593 KB (F17)** e **npm audit 6 high (F19)** — saída direta de
   `npm run build` e `npm audit`.

---

## 7. Segurança e LGPD

- **Autenticação/sessão:** bcrypt + JWT são adequados, mas faltam
  anti-bruteforce (F4), revogação de sessão (F13) e *fail-closed* sem
  `JWT_SECRET` (F5). `/validate/{code}` pública no admin (F20).
- **Autorização:** rotas admin protegidas; CRUD de templates visuais protegido
  no include ([main.py:236-238](certificados-admin/backEnd/main.py)). OK.
- **CORS:** nunca usa `*`; em produção exige `ADMIN_FRONTEND_URL`/`PUBLIC_APP_URL`,
  porém cai em origens localhost (apenas aviso) se desconfigurado
  ([main.py:99-126](certificados-admin/backEnd/main.py)) — combine com F5 para
  "produção silenciosamente insegura".
- **Uploads:** planilha valida extensão/magic/tamanho; imagens validam magic e
  10 MB, mas sem limite de pixels/DoS (F15).
- **LGPD:** a consulta oculta e-mail/documento (`_public_view`), o que é bom.
  Porém **a exposição do código + download só-por-código (F7)** permite que
  qualquer pessoa correlacione nome→certificado→PDF (que contém nome e o texto
  do certificado). Avaliar base legal, minimização e necessidade de barreira
  adicional no download. **Higiene de dados (F23):** há planilha/PDFs reais no
  diretório, com `data/` fora do `.gitignore`.
- **Integridade:** checksum não verificado no download (F12); sem confinamento
  forte de path no local (F21).

---

## 8. Banco, storage, consistência e concorrência

- **Esquema:** colunas bem pensadas, mas **sem constraints de domínio nem FKs**
  (F16). Índices criados após migração de colunas (correto)
  ([db.py:122-151](database/db.py)).
- **Datas:** armazenadas por extenso e usadas para ordenar (F8). `start_date`/
  `end_date` idem. Sem coluna ISO para ordenação/índice.
- **Concorrência:** conexões abrem/fecham por chamada; WAL habilitado; **mas**
  geração e alocação de código não são transacionais (F1/F2). `init_db()` roda a
  cada `save_certificates` ([certificate_store.py:62](certificados-admin/backEnd/services/certificate_store.py)) — custo desnecessário.
- **Idempotência:** `business_key` com índice UNIQUE é uma boa decisão, mas a
  verificação fora de transação a torna não confiável sob concorrência (F2).
- **Storage:** abstração limpa; Drive com escopo `drive.file` (mínimo
  privilégio) — bom. **Órfãos:** reemissão no Drive não apaga o anterior (F6);
  falha parcial de lote deixa órfãos (F1). Checksum não verificado (F12).
- **Backup/recuperação:** inexistentes como processo; README cita "backup diário"
  como recomendação, sem implementação.

---

## 9. Frontend, UX e acessibilidade

- **Build/TS:** `tsc -b` passa; tipos coerentes. **Bundle** único grande (F17).
- **Fluxo Emitir:** bom (upload → preview → gerar) com estados de carregamento.
- **Histórico:** filtros e paginação OK; **sem download em lote** (F22);
  revogação por `window.prompt`/`alert` (F25); o link "Baixar" depende do cookie
  HttpOnly em navegação top-level (funciona, mas frágil se a sessão expirar).
- **Acessibilidade:** há `aria-label` em filtros, mas diálogos nativos e
  feedbacks são limitados; faltam mensagens de erro específicas e foco
  gerenciado.
- **Editor visual:** rótulo "Evento/Curso" reforça a confusão semântica do F9.

---

## 10. Testes ausentes ou insuficientes

A suíte (77 testes) cobre normalização de datas, storage (local + Drive fake),
planilha/validação, geração+idempotência+QR, auth e rotas protegidas,
histórico/revogação e parte da consulta. **Lacunas relevantes:**

- **Contrato QR↔rota pública** (teria pego o F3). Adicionar teste que monta o QR
  e confirma que a rota correspondente existe e responde.
- **Concorrência** na geração/alocação de código (F1/F2): testes simulando
  `business_key`/código em corrida e falha parcial de storage.
- **Ordenação cronológica** do histórico/consulta (F8).
- **Curingas/acentos** na busca (F10).
- **Reemissão** preservando template/aparência e não deixando órfãos (F6).
- **Verificação de checksum** no download (F12).
- **Anti-bruteforce** no login (F4) e *fail-closed* sem `JWT_SECRET` (F5).
- **Uploads maliciosos** (imagem bomba / data URL grande / planilha com muitas
  linhas) (F15).
- **E2E/integração do frontend** (não há testes de frontend).

---

## 11. Documentação e configuração divergentes

- **README × código:** README afirma que o QR aponta para `…/validar/{code}`
  ([README.md:180](README.md)) e lista `/certificado/{code}/download` como rota
  pública ([README.md:303](README.md)); a rota `/validar/{code}` **não existe**
  (F3).
- **"Um template padrão" × realidade:** o objetivo descreve um template padrão
  único; o código tem **três** estratégias (padrão, por curso, visual). A tabela
  do README ([README.md:49-61](README.md)) descreve um esquema antigo/reduzido
  da tabela `certificates` (sem `course_name`, `business_key`, `status`, storage,
  lifecycle), desatualizado frente ao [schema.sql](database/schema.sql).
- **`.env.example`:** documenta `PUBLIC_VALIDATION_BASE_URL/validar/<codigo>`
  ([.env.example:17-18](.env.example)) — mesma divergência do QR.
- **Fluxo legado:** `/generate-certificates` permanece documentado/exposto
  (F14), gerando ambiguidade sobre qual é o caminho canônico.
- **Artefatos antigos:** `certificados-admin/backEnd/output/certificados/*.pdf`
  são de versões anteriores (não referenciados pelo banco) — o próprio README
  reconhece ([README.md:394-396](README.md)).

---

## 12. Arquitetura recomendada para deploy separado

Para sustentar **dois deploys realmente independentes** (admin interno e
consulta pública):

1. **Banco gerenciado** (PostgreSQL) no lugar do SQLite compartilhado —
   resolve concorrência, FKs, índices e backup; remove a dependência de
   filesystem comum (F18). Camada `database/db.py` precisaria virar uma camada
   com driver/conn pool.
2. **Storage de objetos** como única fonte dos PDFs (Google Drive já previsto,
   ou S3/GCS) — elimina o filesystem local como dependência cruzada.
3. **Consulta pública isolada**: somente leitura, atrás de WAF/rate limit na
   borda (nginx/Cloudflare), sem acesso a colunas administrativas — idealmente
   uma *view*/role de leitura restrita.
4. **Admin em rede interna/VPN**, HTTPS obrigatório, `APP_ENV=production`,
   `JWT_SECRET` exigido (fail-closed), CORS restrito.
5. **Transações de geração** com escrita atômica (storage → confirmação →
   commit) ou padrão *outbox*/compensação para evitar órfãos (F1/F2/F6).
6. **Backup/restore** automatizado do banco e verificação periódica de
   integridade (checksum) dos PDFs no storage (F12).
7. **Observabilidade**: logs estruturados, métricas de geração/erros, e
   alertas para falhas de storage.

> Alternativa pragmática (menor esforço): manter **um único deploy** (monólito)
> e **documentar** que admin e consulta não são independentes hoje — alinhando
> expectativa ao código.

---

## 13. Roadmap

### 13.1 Impeditivos antes de produção (bloqueadores)
1. **F1/F2** — tornar geração e alocação de código transacionais; eliminar
   "sucesso falso" e órfãos.
2. **F3** — corrigir o QR/rota `/validar` (validação pública funcional).
3. **F5** — *fail-closed* sem `JWT_SECRET` em produção.
4. **F4** — proteção contra força bruta no login.
5. **F8** — ordenação cronológica correta (coluna de data ISO).
6. **F7** — mitigar enumeração/LGPD no download público.
7. **F6** — reemissão consistente (template/snapshot) e sem órfãos no Drive.

### 13.2 Curto prazo
- **F9** (evento×curso visual), **F10** (curingas/acentos), **F11** (rate limit/
  proxy), **F12** (verificar checksum), **F13** (revogação de sessão),
  **F20** (`/validate` pública no admin), **F19** (`npm audit fix`).

### 13.3 Médio prazo
- **F14** (depreciar fluxo legado), **F16** (constraints/FKs), **F15** (uploads/
  DoS), **F22** (UI de download em lote), **F17** (code splitting), **F23**
  (higiene de dados), atualizar **documentação** (seção 11).

### 13.4 Melhorias opcionais
- **F18** (migrar para Postgres + storage de objetos), **F21** (confinamento de
  path), **F24** (CSRF explícito), **F25** (UX/acessibilidade), testes de
  frontend/E2E, CI com lint+audit+testes.

---

## 14. Perguntas que precisam de decisão do responsável

1. **Template padrão:** o objetivo é mesmo **um template global único**, ou as
   três estratégias (padrão/curso/visual) são desejadas? Isso define se o atual
   é "incompatível" ou "feature".
2. **QR:** a validação pública deve ser uma **página HTML** (`/validar/{code}`)
   ou o QR deve apontar para a API `/public/verify/{code}`?
3. **Download público (LGPD):** o código pode continuar sendo a **única**
   credencial de download, ou exige fator adicional (documento/data)?
4. **Reemissão:** deve **reproduzir fielmente** o template original (snapshot) ou
   é aceitável reemitir sempre com o layout corrente?
5. **Deploy:** admin e consulta precisam ser **realmente independentes**
   (justifica Postgres + storage de objetos) ou um único host é aceitável?
6. **Datas:** o "por extenso" é requisito de exibição? (a recomendação é manter
   exibição por extenso + coluna ISO para ordenação/índice).
7. **Fluxo legado** `/generate-certificates`: pode ser **removido**?
8. **Retenção/auditoria:** política de retenção de `certificates` e `audit_log`,
   e se a auditoria precisa de IP/encadeamento à prova de adulteração.

---

## 15. O que corrigir primeiro (ordem recomendada)

1. **F1** — Geração transacional (storage + banco) sem "sucesso falso"/órfãos.
2. **F2** — Alocação de código e `business_key` atômicas (à prova de
   concorrência).
3. **F3** — Rota/QR de validação pública (`/validar/{code}`).
4. **F5** — Abortar start em produção sem `JWT_SECRET`.
5. **F4** — Anti-bruteforce no `/auth/login`.
6. **F8** — Data ISO para ordenação cronológica.
7. **F7** — Barreira/avaliação LGPD no download público por código.
8. **F6** — Reemissão fiel ao template + remoção/versionamento de órfãos no Drive.
9. **F12** — Verificar checksum no download.
10. **F9** — Corrigir evento×curso em templates visuais.

> Itens 1–4 são bloqueadores de produção de maior risco (integridade/validação/
> segredo). Os demais reduzem risco operacional, jurídico (LGPD) e de qualidade.

---

### Anexo — Verificações executadas (seguras)

| Verificação | Comando | Resultado |
|---|---|---|
| Testes backend | `python -m pytest tests -q` | **77 passed**, 11 warnings (`InsecureKeyLengthWarning`). |
| Build + TS frontend | `npm run build` (`tsc -b && vite build`) | Compila; **bundle 593.12 kB** (>500 kB). |
| Import consulta | `import app` + listagem de rotas | OK; **sem** `/validar/{code}`. |
| Import admin | `create_app()` (via testes) | OK. |
| Datas/curingas | script em banco **temporário** | Ordem cronológica errada; `%`/`_` curingas — confirmados. |
| Dependências JS | `npm audit --omit=dev` | 8 vulnerabilidades (**6 high**), ex. `ws`. |
| Git | `test -d .git` | **Não** é repositório git. |

> Nenhum dado real, banco, PDF ou arquivo de configuração foi alterado. As provas
> dinâmicas usaram diretório/banco temporários.
