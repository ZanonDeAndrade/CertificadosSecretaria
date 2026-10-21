# Relatório de prontidão final

> **Registro histórico da auditoria de 13/08/2026.** A implementação de pasta
> dinâmica por evento e a migration `0009`, acrescentadas em 14/08/2026,
> alteraram a árvore depois do commit abaixo. Portanto, este relatório não
> certifica o checkout atual nem autoriza produção. A nova integração foi
> validada localmente com fakes, mas ainda exige OAuth, Picker e permissões reais
> em staging e uma nova auditoria limpa completa antes de qualquer deploy.

**Data da auditoria:** 13 de agosto de 2026 (America/Sao_Paulo)

**Escopo:** entrega acadêmica local, sem deploy

**Veredito:** **APTO para demonstração acadêmica; NÃO APTO para produção**

**Dados usados:** exclusivamente sintéticos

O veredito acadêmico foi emitido porque nenhum critério impeditivo permaneceu:
não houve vulnerabilidade alta/crítica conhecida, segredo ou PII detectados no
artefato; instalação limpa, migrations, fluxos críticos, negação de acesso e
restore foram aprovados. Isso não é autorização para implantação.

## Commit auditado e proveniência

- commit do checkout sanitizado após o ajuste da fixture do scanner:
  `08b776ad6488b2b2728ecb18001cac9afacd2203`;
- commit usado no build inicial das imagens:
  `17c64e13d137a584778526fae1eb6972ed0dd3d7`;
- a diferença entre eles é somente o valor sintético de uma chave de
  idempotência em teste. O teste afetado foi reexecutado e aprovado;
- o commit final do ZIP, que acrescenta apenas este relatório, suas evidências e
  o teste de exclusão de documentos históricos, é registrado na seção
  "Fechamento do artefato" após a exportação.

O diretório de desenvolvimento original possuía muitas alterações ainda não
consolidadas e metadados Git antigos corrompidos. Eles foram preservados. A
auditoria ocorreu em repositório Git temporário criado apenas com a árvore
selecionada, commit único e checkout limpo. Nesse checkout, `git status`,
`git diff --check` e `git fsck --full --no-dangling` passaram.

## Ambiente

| Item | Versão/identificação |
|---|---|
| host | Linux 7.0.0-28-generic, x86_64 |
| Git | 2.53.0 |
| Python | 3.12.13 |
| uv | 0.12.3 |
| Node/npm de contrato | 20.20.2 / 10.8.2, executados em container por digest |
| Docker/Compose | 29.6.2 / v5.3.1 |
| PostgreSQL | 16.14 Alpine 3.24, imagem por digest |
| Trivy | 0.67.2, base baixada em 13/08/2026 |
| Gitleaks | 8.28.0 |

Digests das ferramentas de container: Node
`sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0`,
PostgreSQL
`sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`,
Trivy
`sha256:e2b22eac59c02003d8749f5b8d9bd073b62e30fefaef5b7c8371204e0a4b0c08`
e Gitleaks
`sha256:cdbb7c955abce02001a9f6c9f602fb195b7fadc1e812065883f695d1eeaba854`.

## Comandos, resultados e evidências

Variáveis sensíveis e chaves sintéticas foram omitidas dos comandos abaixo.
Os relatórios de máquina completos ficaram fora do ZIP por conterem caminhos e
detalhes efêmeros; o resumo versionado está em
`docs/evidencias/AUDITORIA_FINAL_2026-08-13.json`.

| Gate | Comando executado (resumido) | Resultado observado |
|---|---|---|
| Git limpo | `git status --porcelain`; `git diff --check`; `git fsck --full --no-dangling` | aprovado; zero alteração/erro |
| scanner interno | `python -m scripts.security_scan --repository --permissions` | zero achado |
| scanner independente | `gitleaks git /repo --redact --exit-code=1` | 1 commit, 2,08 MB, zero leak |
| instalação Python | `uv sync --frozen --group dev` | 89 pacotes instalados do lock |
| instalação frontend | Node 20 por digest; `npm ci` | 233 pacotes; aprovado |
| lint/formatação | `ruff check .`; `ruff format --check .` | 132 arquivos; aprovado |
| typecheck Python | `mypy certificados-admin/backEnd certificados_consulta database storage_service observability` | 74 arquivos; zero erro |
| backend | `pytest certificados-admin/backEnd/tests` | 271 passaram; 10 condicionais PostgreSQL ignorados nessa rodada |
| cobertura backend | `pytest --cov --cov-fail-under=70` | 270 passaram, 10 ignorados; 73,83%; gate 70% aprovado antes do teste adicional de exportação |
| PostgreSQL | três arquivos condicionais com `TEST_DATABASE_URL` | os mesmos 10 testes passaram; zero skip/falha |
| migrations SQLite | upgrade `0001→0008`, check, downgrade `0008→0007`, reupgrade e check | aprovado |
| migrations PostgreSQL | upgrade/check/downgrade/reupgrade/check; restore também em `0008` | aprovado |
| frontend | `npm run typecheck`; `npm test`; `npm run build` | tipos aprovados; 35 testes; build aprovado |
| E2E | `playwright test` em desktop/mobile | 94 passaram; 4 skips condicionais por projeto; zero falha |
| acessibilidade | specs axe admin+público em desktop/mobile | 51 passaram; 1 skip condicional; zero violação axe executada |
| dependências Python | `pip-audit -r requirements/dev.txt` e `ops.txt` | zero vulnerabilidade conhecida |
| dependências JS | `npm audit --audit-level=high` | zero vulnerabilidade |
| imagens | builds runtime, operações e web; inspeção de usuário; import read-only | aprovados; usuários `10001:10001`, `postgres`, `101:101` |
| scanner de containers | Trivy `HIGH,CRITICAL`, runtime/ops/web e config | zero vulnerabilidade e zero misconfiguration alta/crítica |
| build reprodutível | dois wheels com o mesmo `SOURCE_DATE_EPOCH`; `cmp` | bytes idênticos; SHA-256 `780407e472daedf5c2f8dfed341b07500ffc82068321cd4bb2716a5da146d6a3` |
| backup/restore | backup cifrado de PostgreSQL+PDF; restore em banco/storage descartáveis; verificação | 1 PDF restaurado e verificado; 1 certificado; 4 eventos; aprovado em 0,315 s |
| smoke local | APIs reais + PostgreSQL + storage local, com `Origin` permitido | health, login, emissão, validação, integridade, download e revogação aprovados |
| acesso negativo | detalhe admin sem sessão e download público após revogação | HTTP 401 e 410, respectivamente |
| PDF final | `pdfinfo`, `pdftotext`, rasterização e inspeção visual | 9 páginas A4; 687.327 bytes; texto e telas legíveis |

Os quatro skips do E2E completo não escondem um fluxo falho: drawer foi
executado somente no projeto mobile; editor canvas e skip link de teclado,
somente no desktop. Os 10 skips do backend foram executados em uma rodada
PostgreSQL separada e todos passaram.

### Imagens produzidas e escaneadas

| Imagem | Digest local | Tamanho |
|---|---|---:|
| runtime | `sha256:df4d3b385ac21ce7b16c8dc72130903c4b1520a1df92e416c77f85566b5215be` | 124.229.656 B |
| operações | `sha256:7fd943aaf20bf58dbf7fdbebda3a4dadd37aa7613721748bf8a24ee8dee70f32` | 238.380.994 B |
| web | `sha256:2751d353840e26feeae4ab514a5f1abaf33578af95a21c78046b0ff4564b357c` | 23.283.982 B |

O smoke da imagem web confirmou o SPA administrativo. A rota pública depende
por projeto de upstream separado; o smoke funcional público foi executado com
as duas aplicações reais.

## Evidência de backup e recuperação

O job de operações criou dois artefatos cifrados AES-256-GCM usando chave
sintética: dump PostgreSQL e pacote de PDFs. O restore foi feito em banco e
storage descartáveis, não sobre a origem. Resultado:

- `admin_users=1`, `emission_batches=1`, `certificates=1`, `audit_log=4`;
- 1 PDF restaurado e 1 verificado por integridade;
- migration restaurada em `0008` e `alembic check` aprovado;
- duração observada de 0,315 s, sem uso como promessa de RTO.

O registro sanitizado está em
`docs/evidencias/RESTORE_DRILL_2026-08-13.json`. Os arquivos cifrados de teste e
a chave efêmera não integram a entrega.

## Riscos residuais e itens aceitos conscientemente

- Google Drive real não foi acessado; escopos, pasta privada, conta somente
  leitura e cotas ainda precisam de staging.
- Não houve deploy, tráfego real, teste de carga com meta institucional, pentest
  independente nem validação jurídica/LGPD.
- Axe automatizado não substitui teste manual com teclado, zoom, contraste e
  leitor de tela.
- Há dois avisos não bloqueantes: deprecação futura do `TestClient` Starlette e
  de `Pillow.Image.getdata` em teste; não são falhas nem vulnerabilidades altas.
- O scanner representa as bases disponíveis em 13/08/2026; novas CVEs exigem
  nova auditoria.
- SQLite permanece apenas para desenvolvimento/testes. Produção exige
  PostgreSQL.
- O PDF possui checksum de integridade, não assinatura digital ICP-Brasil.
- RPO, RTO, SLO, retenção, base legal, custos e cotas dependem de decisão da
  instituição; não foram inventados.
- O repositório Git original precisa de saneamento/backup separado. Esse risco
  não está presente no ZIP exportado do checkout limpo.

## Checklist para demonstração acadêmica

- [x] ZIP derivado somente de arquivos versionados no checkout limpo;
- [x] scanner do repositório, Gitleaks e scanner do ZIP sem achados;
- [x] dados e screenshots exclusivamente sintéticos;
- [x] migrations SQLite/PostgreSQL e fluxo principal aprovados;
- [x] autenticação/RBAC e controle de acesso negativo aprovados;
- [x] backup restaurado em alvo descartável e PDF verificado;
- [x] relatório final, PDF, diagramas, manuais e matrizes presentes;
- [x] documento de junho preservado somente como histórico obsoleto e excluído
  do ZIP;
- [x] roteiro offline disponível, sem dependência de Drive real;
- [x] nenhuma alegação de deploy ou prontidão de produção.

## Checklist separada para produção

- [ ] staging com PostgreSQL/Drive/segredos reais e somente dados sintéticos;
- [ ] responsáveis LGPD, base legal, retenção e direitos aprovados;
- [ ] RPO, RTO, SLO, alertas e on-call aprovados;
- [ ] credenciais separadas, cofres, rotação e revogação ensaiadas;
- [ ] backup externo e restore drill operacional recorrente;
- [ ] pentest/revisão de segurança e acessibilidade manual;
- [ ] teste de carga com metas e volume aprovados;
- [ ] rollback/migration ensaiados e janela aprovada;
- [ ] custos, cotas e orçamento aprovados;
- [ ] monitoração, runbooks, suporte e resposta a incidente aprovados;
- [ ] aprovação formal para deploy.

## Fechamento do artefato

O último commit foi novamente submetido a Git fsck, scanner interno e Gitleaks;
o ZIP foi submetido ao scanner de artefato. Todos foram aprovados. O hash desse
commit, o SHA-256 e o tamanho do ZIP são informados na entrega externa para
evitar autorreferência impossível dentro do próprio artefato.
