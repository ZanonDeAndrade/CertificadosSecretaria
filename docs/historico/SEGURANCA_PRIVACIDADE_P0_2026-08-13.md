# Segurança e privacidade P0

Data da implementação local: 2026-08-13.

Este documento registra somente classes, caminhos e nomes de configuração.
Nenhum valor de credencial foi lido, reproduzido, validado ou enviado a serviços
externos. Nenhuma rotação, migration remota ou implantação foi executada.

## Credenciais que exigem rotação manual

| Ordem | Material constatado no pacote local | Recurso externo a identificar antes da ação | Impacto esperado | Rollback controlado |
|---|---|---|---|---|
| 1 | `secrets/google_oauth_token.json` e cópia `(2)` | autorização OAuth/refresh token usada pelo Drive administrativo | revogar interrompe uploads, downloads e reconciliação que ainda dependam do token antigo | provisionar e testar credencial administrativa nova antes da revogação; durante rollback, restaurar apenas a versão anterior do secret se ela ainda não tiver sido revogada |
| 2 | `secrets/service_account.json` e cópia `(2)` | chave da Service Account indicada pelo campo de identidade do JSON, sem expô-lo neste relatório | excluir a chave antes da troca interrompe o acesso do workload correspondente | criar chave/identidade substituta com permissão restrita, testar, trocar o secret e só então desativar a chave exposta |
| 3 | `.env` e `secrets/database_url` | usuário/senha PostgreSQL contido na URL | troca antecipada derruba admin, consulta, migrations e backup | criar credencial substituta com os mesmos grants mínimos, atualizar workloads e validar readiness antes de revogar a anterior |
| 4 | `.env` e `secrets/jwt_secret` | secret de assinatura das sessões administrativas | rotação invalida sessões existentes | janela de manutenção, comunicação de novo login e restauração temporária da versão anterior somente se a exposição ainda permitir esse risco |
| 5 | `.env` e `secrets/document_hash_secret` | chave `v1` de HMAC dos documentos | remoção imediata impede validar hashes antigos cujo texto puro já foi minimizado | manter `v1` na keyring até que nenhum registro dependa dela; nunca substituir o valor de `v1` |

Os identificadores de conta, projeto, banco e Service Account não foram
extraídos dos arquivos, conforme a restrição de não abrir credenciais. Antes de
qualquer mutação externa, o operador deve apresentar o identificador exato do
recurso, o impacto, a janela e o rollback e obter confirmação explícita.

## Rotação segura do HMAC de documento

A migration `0006` adiciona `participant_document_hash_key_id` e marca hashes
preexistentes como `v1` sem alterar seus bytes. O serviço aceita uma keyring JSON
montada por secret file e escreve novos hashes com
`DOCUMENT_HASH_ACTIVE_KEY_ID`.

Procedimento futuro, deliberadamente não executado nesta etapa:

1. Criar uma keyring fora do repositório contendo `v1` com a chave antiga e
   `v2` com uma chave aleatória nova e distinta.
2. Montá-la como `DOCUMENT_HASH_KEYRING_FILE`, mantendo
   `DOCUMENT_HASH_ACTIVE_KEY_ID=v1`, aplicar a migration em ambiente autorizado
   e validar a leitura dos registros existentes.
3. Trocar apenas o identificador ativo para `v2`. Novos certificados passam a
   gravar `v2`; hashes `v1` continuam verificáveis.
4. Quando uma pessoa confirma documento/matrícula corretamente, o backend
   recalcula o HMAC com `v2` e atualiza apenas hash + versão, nunca o texto puro.
5. Medir, no banco autorizado, quantos registros ainda usam `v1`. Certificados
   sem documento cadastrado não entram nesse fluxo e não podem ser baixados por
   nome.
6. Remover `v1` somente após contagem zero, backup testado e aprovação formal.

Rollback: voltar `DOCUMENT_HASH_ACTIVE_KEY_ID` para `v1` mantendo ambas as
chaves. Registros já migrados para `v2` continuam válidos enquanto `v2`
permanecer na keyring.

## Decisão de produto para consulta pública

- A validação por código permanece pública e é a rota canônica do QR Code.
- Busca por nome usa somente `POST`, retorna nome mascarado e metadados mínimos,
  sem código, URL direta ou `download_challenge`.
- `result_ref` é apenas um seletor opaco e domain-separated; isoladamente ele
  nunca autoriza download.
- Download originado da busca exige documento ou matrícula. A comparação usa o
  HMAC versionado e `hmac.compare_digest`.
- Ausência de hash, dado incorreto, referência inválida e certificado inexistente
  recebem a mesma resposta genérica. Certificados sem documento/matrícula exigem
  atendimento da secretaria.
- Nome, documento e matrícula não entram em URL. Respostas sensíveis usam
  `Cache-Control: no-store, private`; proxy e aplicação não registram corpos.
  Os access logs HTTP brutos do proxy e do Uvicorn ficam desativados para que
  query strings enviadas por clientes legados também não persistam PII.
- Rate limit usa banco compartilhado, com buckets por IP e por identidades
  pseudonimizadas por HMAC, funcionando entre workers.

Base de segurança: minimização e necessidade da LGPD; OWASP ASVS 2.1, 2.2, 3.4,
4.1, 5.1, 7.1, 9.1 e 13.2; prevenção de BOLA/capabilities reutilizáveis da OWASP
API Security Top 10.

## Separação do Google Drive

Produção falha no startup se o admin não usar `read_write` com variáveis
`GOOGLE_ADMIN_*`, ou se o serviço público não usar `read_only` com variáveis
`GOOGLE_PUBLIC_*`. O cliente público solicita escopo `drive.readonly` e bloqueia
`save`/`delete` em código; quando a credencial declara escopos, qualquer conjunto
mais amplo que o exigido pelo perfil é rejeitado. O ideal operacional é uma identidade dedicada que
tenha papel de leitor somente na pasta dos certificados; o admin/jobs mantém uma
identidade distinta com escrita.

Em produção, registros legados sem `drive_file_id` também falham de forma
fechada: o serviço não tenta ler um caminho local. Eles devem ser reconciliados
em processo autorizado antes de ficarem disponíveis novamente.

## Entrega acadêmica reprodutível

```bash
python3 -m scripts.security_scan --repository --permissions --history
python3 -m scripts.export_release /tmp/certificados-academic-release.zip
python3 -m scripts.security_scan --artifact /tmp/certificados-academic-release.zip
```

O exportador usa somente paths presentes no índice Git (`git ls-files`), lê o
conteúdo atual desses paths, normaliza timestamps/permissões e exclui
`.git`, `.env*` (exceto exemplos), credenciais, dados, bancos, planilhas, PDFs,
logs, caches, builds, dependências, configurações locais e cópias `(2)`. O ZIP é
apagado automaticamente se a verificação redigida encontrar uma violação.
