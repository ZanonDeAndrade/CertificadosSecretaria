# Política de segurança e LGPD

Este documento é uma política técnica do projeto, não parecer jurídico. A
instituição controladora deve definir base legal, avisos, prazos e responsáveis
com seu encarregado de dados antes de uso real.

## Princípios

- finalidade e necessidade: coletar somente campos necessários à emissão;
- minimização: não devolver documento, e-mail, IDs internos ou links Drive;
- acesso mínimo: papéis e credenciais distintas para escrita e leitura;
- segurança por padrão: produção falha ao iniciar com configuração insegura;
- rastreabilidade: ações relevantes entram em auditoria minimizada;
- retenção limitada: dados e payloads temporários têm ciclo definido;
- recuperação verificável: backup só é considerado válido após restore drill.

## Categorias e tratamento

| Categoria | Exemplos | Finalidade | Proteção |
|---|---|---|---|
| identificação acadêmica | nome, documento/matrícula | emitir e confirmar download por busca | acesso restrito; documento em HMAC versionado; resposta pública mascarada. |
| acadêmica | curso, evento, carga, datas | compor e validar certificado | metadados mínimos na área pública. |
| arquivo | PDF do certificado | prova acadêmica | Drive privado, proxy e SHA-256. |
| administrativa | usuário, papel, sessão | autenticar e autorizar | bcrypt, cookie seguro, revogação e RBAC. |
| telemetria | correlação, ação, horário | operar e investigar | logs sem corpo, segredos ou identificadores desnecessários. |

## Regras obrigatórias

Senhas administrativas novas exigem ao menos 6 caracteres, com maiúscula,
minúscula, número e caractere especial. Nome de usuário, senhas comuns,
caracteres de controle e entradas acima de 72 bytes são rejeitados. Rate limit,
bloqueio temporário, sessões revogáveis e troca obrigatória de senha temporária
continuam obrigatórios; complexidade curta não os substitui.

1. Nunca usar planilha, screenshot, banco ou PDF real em teste, demonstração,
   issue, commit, log ou ZIP acadêmico.
2. Segredos ficam em Secret Manager/arquivos montados, com permissão mínima;
   exemplos contêm somente placeholders.
3. HTTPS é obrigatório em produção, inclusive PostgreSQL com verificação
   de certificado conforme a configuração documentada.
4. O backend é a autoridade de acesso. Esconder botão no frontend não autoriza.
5. Busca nominal usa `POST`, `Cache-Control: no-store` e confirmação adicional;
   código e PDF não são devolvidos no resultado nominal inicial.
6. Certificado revogado, ausente, corrompido ou com integridade não comprovada
   não é servido.
7. Auditoria usa allowlist e não registra senha, token, documento, corpo integral,
   arquivo ou motivo livre que possa conter dado excessivo.
8. Conta inativa e mudança sensível revogam sessões aplicáveis.
9. A chave HMAC, a chave de jobs e a chave de backup são distintas e versionadas.
10. Incidente de exposição exige contenção, preservação de evidência,
    rotação coordenada e avaliação pelo encarregado/controlador.

## Direitos e operações do titular

O software não automatiza sozinho todos os direitos LGPD. Solicitações de
acesso, correção, oposição ou eliminação devem entrar por processo
institucional autenticado. A secretaria deve avaliar obrigações de guarda e,
quando a eliminação não for cabível, aplicar bloqueio/restrição e registrar a
decisão. Revogação do certificado não equivale automaticamente a eliminação.

## Retenção

O campo institucional `retention_days` fornece configuração, mas a instituição
deve definir o prazo jurídico real. Payloads cifrados de jobs concluídos devem ser
limpos pelo job de manutenção; sessões e rate limits expirados também. Backups
precisam expirar de modo coerente, considerando restaurações e legal hold.

## Resposta a incidente

1. bloquear o vetor e preservar logs minimizados;
2. identificar dados, titulares, período e ambientes afetados;
3. revogar sessões e rotacionar material exposto sem perder chaves históricas
   ainda necessárias;
4. validar integridade de banco, PDFs, templates e backups;
5. acionar controlador/encarregado para decidir comunicações aplicáveis;
6. registrar causa, correção, testes negativos e prevenção de recorrência.
