# Modelo de ameaças

Método: STRIDE por ativo e limite de confiança. Escopo: código atual e uma
implantação hipotética corretamente configurada. Não houve pentest nem teste
contra serviços reais.

## Ativos

- credenciais administrativas, sessões e papéis;
- dados pessoais e acadêmicos;
- PDFs, códigos e hashes de integridade;
- chaves JWT, HMAC de documento, cifra de jobs e backup;
- credenciais do PostgreSQL e Google Drive;
- templates, configurações institucionais e trilha de auditoria;
- disponibilidade do fluxo de emissão e validação.

## Ameaças e controles

| ID | STRIDE | Cenário | Controle atual | Risco residual / ação |
|---|---|---|---|---|
| T01 | S | força bruta ou credencial reutilizada | bcrypt, mensagem genérica, throttle persistente por identidade/IP, sessão revogável | não há MFA; avaliar IdP/MFA. |
| T02 | E | secretaria chama endpoint de admin ou auditor altera dados | RBAC central no backend e testes negativos | revisar nova rota contra `policies.py`; interface não é autoridade. |
| T03 | T | PDF alterado no storage | assinatura `%PDF`, tamanho, SHA-256 e bloqueio de integridade | SHA-256 detecta alteração, mas não é assinatura digital jurídica. |
| T04 | T/R | lote repetido, concorrente ou parcialmente concluído | Idempotency-Key + request hash, business key, constraints, saga, lease/retry, auditoria | indisponibilidade longa exige operador e reconciliação. |
| T05 | I | busca nominal enumera pessoa/certificado | POST, resposta minimizada/mascarada, referência opaca, confirmação HMAC, rate limit | nomes ainda são dados pessoais processados no request; política de logs é obrigatória. |
| T06 | I | link, ID ou credencial do Drive exposta | pasta privada e download por proxy; access token curto apenas em memória para o Picker; API pública sem IDs | permissões externas da pasta precisam de revisão operacional. |
| T07 | I | segredo entra em Git, log ou ZIP | arquivos ignorados, scanner redigido, gitleaks no CI, exportador allowlist | scanner não substitui rotação nem revisão humana. |
| T08 | D | XLSX/PNG malformado consome memória/CPU | limites de upload, linhas, colunas, célula, tempo, OOXML e decompression bomb | geração e ZIP ainda exigem limites operacionais e monitoramento. |
| T09 | D | rate limit contornado por workers | contador compartilhado no PostgreSQL e validação de proxy confiável | ataque distribuído precisa de proteção na borda/WAF. |
| T10 | S/I | token JWT roubado | cookie HttpOnly/Secure em produção, TTL, `jti`, revogação e mudança de senha | XSS/endpoint comprometido ainda exige resposta a incidente. |
| T11 | T | payload de job no banco adulterado | AES-GCM com AAD, key id e falha fechada auditada | disponibilidade depende da keyring; backup/rotação devem preservar chaves antigas. |
| T12 | R | ator nega revogação/reemissão | audit log com ator, alvo, data e detalhes allowlist | log não é encadeado/assinado; acesso DBA pode alterá-lo. |
| T13 | I/T | backup roubado ou restaurado no banco errado | AES-256-GCM, destino dedicado, restore somente em alvo descartável nomeado | custódia da chave e bucket deve ser independente. |
| T14 | E | SSRF/path traversal por localizador de arquivo | Drive usa file id; storage local confina o path; produção falha fechada sem file id | manter testes de confinamento. |
| T15 | S/T | callback OAuth forjado, state reutilizado ou redirect adulterado | state aleatório hasheado e consumido uma vez, PKCE, callback/retorno fixos, cookie e validação de origem | comprometimento da conta Google ainda exige revogação operacional. |
| T16 | E/I | pasta pública ou identidade de consulta recebe escrita | nunca cria `anyone`; principals técnicos distintos writer/reader; startup falha se colapsados | administrador do Drive pode alterar permissões fora do sistema. |

## Abuso prioritário

1. buscar nomes comuns em volume e tentar confirmar documentos;
2. repetir confirmação de lote com chave diferente para forçar duplicidade;
3. roubar conta de secretaria e emitir/revogar;
4. adulterar metadado de arquivo ou bytes no Drive;
5. comprometer a credencial Drive de escrita;
6. restaurar backup sobre banco não descartável;
7. inserir segredo/PII em commit ou artefato acadêmico.

## Critérios de revisão

O modelo deve ser revisto ao adicionar nova integração, nova categoria de dado,
login federado, assinatura digital, envio de e-mail, storage diferente, endpoint
público ou mudança na topologia. Ameaça alta/crítica sem mitigação aceita por
responsável bloqueia produção.
