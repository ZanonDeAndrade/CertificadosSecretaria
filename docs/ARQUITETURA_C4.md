# Arquitetura C4

Versão documental: 14 de agosto de 2026. Os diagramas usam Mermaid e descrevem
o código versionado, não um ambiente implantado.

## Nível 1 — contexto

```mermaid
flowchart LR
    secretaria[Pessoa da secretaria] -->|HTTPS; opera lotes e histórico| sistema[CertificadosSecretaria]
    admin[Administrador] -->|HTTPS; usuários, configuração e templates| sistema
    auditor[Auditor] -->|HTTPS; consulta somente leitura| sistema
    publico[Aluno ou verificador externo] -->|HTTPS; busca, validação e download condicionado| sistema
    sistema -->|SQL/TLS| pg[(PostgreSQL)]
    sistema -->|Google Drive API; arquivos privados| drive[Google Drive]
    secretaria -->|OAuth 2.0 + Picker oficial| google[Identidade e Picker Google]
    sistema -->|leitura de segredos em runtime| secrets[Gerenciador/arquivos de segredos]
    operador[Operador autorizado] -->|backup, restore drill, migrations e monitoramento| sistema
```

Fora do escopo do sistema: identidade institucional federada, assinatura digital
ICP-Brasil, envio de e-mail e armazenamento público de arquivos. O código não
implementa esses recursos.

## Nível 2 — containers

```mermaid
flowchart TB
    subgraph navegador[Navegador]
      spa[Painel administrativo\nReact + TypeScript]
      picker[Google Picker oficial\nseleção de uma pasta]
    end
    publico[Aplicação pública\nFastAPI + Jinja2]
    api[API administrativa\nFastAPI]
    worker[Worker de emissão\nPython]
    manut[Jobs operacionais\nbackup, integridade, reconciliação]
    edge[Web/reverse proxy\nNginx ou Caddy]
    pg[(PostgreSQL 16\nmetadados, sessões, jobs e auditoria)]
    drive[(Google Drive privado\nPDFs definitivos)]
    secret[(Secret store\nchaves e credenciais)]

    spa -->|JSON/HTTPS /api| edge
    spa -->|token curto somente em memória| picker
    edge --> api
    edge --> publico
    api --> pg
    api -->|enfileira lote persistente| pg
    worker -->|claim/lease/retry| pg
    worker -->|cria/exclui em compensação| drive
    publico -->|consulta metadados| pg
    publico -->|somente leitura; proxy de bytes| drive
    manut --> pg
    manut --> drive
    api -.-> secret
    worker -.-> secret
    publico -.-> secret
    manut -.-> secret
```

Em desenvolvimento, SQLite e storage local substituem PostgreSQL e Drive. Essa
substituição existe para teste local e não é a arquitetura de produção.

## Nível 3 — componentes do backend

```mermaid
flowchart LR
    subgraph adminapi[API administrativa]
      auth[Autenticação e sessões]
      policy[Policies/RBAC]
      routers[Routers e schemas]
      batch[Batch service]
      cert[Certificate service]
      template[Template service]
      audit[Audit service]
      settings[Settings/User services]
      driveauth[Drive integration\nOAuth PKCE, Picker e grants]
    end
    subgraph shared[Camadas compartilhadas]
      repo[Repositories SQLAlchemy]
      crypto[Cifra de payload e HMAC]
      generator[Gerador PDF e QR]
      integrity[Validação PDF/SHA-256]
      storage[CertificateStorage]
      obs[Observabilidade]
    end
    routers --> auth
    routers --> policy
    routers --> batch
    routers --> cert
    routers --> template
    routers --> audit
    routers --> settings
    routers --> driveauth
    batch --> crypto
    batch --> repo
    batch --> cert
    cert --> generator
    cert --> integrity
    cert --> storage
    cert --> repo
    auth --> repo
    template --> repo
    audit --> repo
    settings --> repo
    driveauth --> repo
    driveauth --> storage
    routers --> obs
```

## Decisões e consequências

| Decisão | Motivo | Consequência real |
|---|---|---|
| PostgreSQL como fonte de verdade em produção | transações, concorrência, constraints e workers múltiplos | requer migrations, TLS, backup e operação do banco. |
| PDFs fora do banco | separar metadados de binários e usar Drive privado | não há transação distribuída; a saga deve compensar/reconciliar. |
| API pública separada | superfície e escala distintas | compartilha PostgreSQL e lê arquivos nas pastas registradas, com identidade Drive distinta e somente leitura. |
| uma pasta por evento | impedir mistura entre eventos e manter destino reproduzível | o mapa `evento -> folder_id` entra cifrado no contexto do lote e fica imutável durante retry. |
| sessão server-side mais JWT | logout/revogação efetivos | cada requisição autenticada consulta estado de sessão. |
| lote persistente e cifrado | sobreviver a restart sem gravar planilha em claro | exige chave AES-GCM versionada e rotina de retenção. |
| template imutável por versão | reemissão reproduzível e auditoria | imagens/layout aumentam o banco e precisam de backup. |

## Limites de confiança

1. Internet → reverse proxy: entrada não confiável, TLS e headers restritos.
2. Navegador admin → API: cookie HttpOnly, proteção de origem e RBAC no servidor.
3. Serviços → PostgreSQL: credencial de aplicação e TLS verificado em produção.
4. Serviços → Drive: identidades separadas de escrita e somente leitura.
5. Runtime → secrets: valores nunca entram no repositório nem nas respostas.

O OAuth pessoal usa authorization code com PKCE, `state` aleatório consumido
uma única vez e somente o escopo `drive.file`. Não é armazenado refresh token.
Depois da validação, a pasta permanece privada e é compartilhada somente com
as identidades técnicas configuradas de escrita e leitura.

A migration `0009` adiciona o estado OAuth transitório cifrado e grants de
pastas validados. O mapa evento→pasta fica no contexto AES-GCM do lote, não no
navegador. Cada certificado persiste `drive_folder_id`; retry, reemissão,
consulta, backup e reconciliação usam esse destino original.
