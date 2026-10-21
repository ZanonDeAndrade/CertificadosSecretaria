# Fluxos principais

## Emissão

```mermaid
sequenceDiagram
    actor S as Secretaria
    participant UI as Painel
    participant API as API admin
    participant PG as PostgreSQL
    participant W as Worker
    participant D as Drive privado

    S->>UI: seleciona XLSX sintético/institucional autorizado
    UI->>API: valida planilha (sem emitir)
    API-->>UI: linhas válidas/inválidas, preview e eventos distintos
    S->>UI: conecta conta Google via OAuth 2.0 + PKCE
    UI->>D: abre Google Picker oficial
    S->>UI: escolhe uma pasta para cada evento/grupo sem evento
    UI->>API: envia escolhas de pasta
    API->>D: valida pasta, capacidades e acesso técnico
    S->>UI: confirma explicitamente
    UI->>API: cria lote + Idempotency-Key + mapa evento/pasta
    API->>PG: grava lote, hash, itens e mapa cifrados
    API-->>UI: 202 + identificador do lote
    W->>PG: claim com lease
    loop para cada item
      W->>PG: verifica business_key/certificado existente
      alt duplicado
        W->>PG: marca duplicate sem gerar PDF
      else novo
        W->>PG: recupera a pasta congelada para o evento da linha
        W->>W: gera código, PDF e QR canônico
        W->>PG: reserva metadados pendentes
        W->>D: upload privado na pasta daquele evento
        alt upload e finalização OK
          W->>PG: finaliza ativo + SHA-256/localizador
        else falha
          W->>D: compensa exclusão quando aplicável
          W->>PG: registra falha/retry saneado
        end
      end
    end
    W->>PG: consolida contadores e apaga payload cifrado conforme ciclo
    UI->>API: consulta progresso por polling
    API-->>UI: resumo gerados/duplicados/inválidos/falhos
```

A idempotência do lote exige que uma mesma `Idempotency-Key` represente o mesmo
hash de planilha, parâmetros e destinos; reutilização conflitante recebe `409`.
O backend exige correspondência exata entre os eventos validados e as pastas,
inclusive a chave vazia do grupo **Certificados sem evento**. O mapa cifrado fica
congelado no lote para retry e retomada. O worker possui lease, heartbeat e
tentativas limitadas. A saga é necessária porque PostgreSQL e Google Drive não
compartilham uma transação ACID.

## Reemissão

A reemissão usa o `drive_folder_id` já registrado no certificado, não uma
pasta escolhida em um lote posterior. O novo PDF é criado nessa pasta e
finalizado no PostgreSQL antes da compensação do arquivo anterior. Se o registro
legado não tiver pasta e o storage for Drive, a operação falha fechada em vez de
misturar o documento em um destino atual.

## Validação pública

```mermaid
flowchart TD
    A[Pessoa lê QR ou digita código] --> B[GET /validar/codigo]
    B --> C{registro existe?}
    C -- não --> X[resposta inexistente minimizada]
    C -- sim --> D{estado}
    D -- revogado --> R[exibe revogado; sem download]
    D -- falha ou integridade bloqueada --> I[falha fechada; sem download]
    D -- ativo --> V[exibe metadados públicos mínimos]
    V --> G{download solicitado?}
    G -- sim --> H[backend busca bytes no Drive read-only]
    H --> J{assinatura PDF, tamanho e SHA-256 conferem?}
    J -- não --> I
    J -- sim --> K[stream do PDF; nenhum link Drive]
    G -- não --> F[fim]
```

## Busca nominal

A busca por nome usa `POST`, não devolve o código do certificado e fornece uma
referência opaca que não autoriza download isoladamente. O download originado
dessa busca exige confirmação do Registro Acadêmico (RA) comparada por HMAC. A
consulta também aceita busca direta pelo RA e retorna todos os certificados
relacionados, sem expor o RA na resposta. A resposta para referência inexistente,
dado incorreto e registro sem dado de
confirmação é deliberadamente genérica.
