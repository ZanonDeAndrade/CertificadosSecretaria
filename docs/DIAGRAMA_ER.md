# Diagrama entidade-relacionamento

O diagrama resume as entidades da migration `0009`. Alguns campos operacionais
foram omitidos visualmente; os modelos em `database/models.py` e as migrations
são a fonte de verdade.

```mermaid
erDiagram
    ADMIN_USERS ||--o{ AUTH_SESSIONS : possui
    ADMIN_USERS ||--o{ AUDIT_LOG : executa
    ADMIN_USERS ||--o{ CERTIFICATES : emite_revoga_reemite
    ADMIN_USERS ||--o{ EMISSION_BATCHES : cria
    ADMIN_USERS ||--o{ TEMPLATE_VERSIONS : cria_ativa
    ADMIN_USERS ||--o| INSTITUTIONAL_SETTINGS : atualiza
    ADMIN_USERS ||--o| GOOGLE_DRIVE_CONNECTIONS : conecta
    ADMIN_USERS ||--o{ GOOGLE_DRIVE_FOLDER_GRANTS : seleciona
    EMISSION_BATCHES ||--|{ EMISSION_BATCH_ITEMS : contem
    EMISSION_BATCHES ||--o{ CERTIFICATES : origina
    TEMPLATE_VERSIONS ||--o{ CERTIFICATES : referencia_snapshot

    ADMIN_USERS {
      int id PK
      string username UK
      string password_hash
      string role
      int is_active
      int must_change_password
    }
    AUTH_SESSIONS {
      string session_id PK
      int user_id
      datetime expires_at
      datetime revoked_at
      string ip_hash
    }
    LOGIN_THROTTLES {
      string scope_type PK
      string scope_key PK
      int failures
      datetime blocked_until
    }
    PUBLIC_RATE_LIMITS {
      string bucket_key PK
      int request_count
      datetime window_started_at
    }
    EMISSION_BATCHES {
      string id PK
      string idempotency_key UK
      string request_sha256
      string status
      binary context_ciphertext
      string lease_owner
      int attempt_count
    }
    EMISSION_BATCH_ITEMS {
      int id PK
      string batch_id FK
      int row_number UK
      string business_key
      binary payload_ciphertext
      string status
      string certificate_code
    }
    CERTIFICATES {
      int id PK
      string unique_code UK
      string business_key UK
      string participant_name
      string participant_document_hash
      string batch_id FK
      int template_version_id
      string status
      string drive_file_id
      string drive_folder_id
      string checksum_sha256
      int integrity_blocked
    }
    TEMPLATE_VERSIONS {
      int id PK
      int version_number UK
      text layout_json
      binary background_image
      int is_active UK
    }
    TEMPLATE_VERSION_SEQUENCE {
      int id PK
      int next_number
    }
    INSTITUTIONAL_SETTINGS {
      int id PK
      string institution_name
      string public_url
      int max_batch_rows
      int retention_days
    }
    GOOGLE_DRIVE_CONNECTIONS {
      int user_id PK
      string state_hash UK
      binary pkce_verifier_ciphertext
      binary access_token_ciphertext
      datetime token_expires_at
      string account_email
    }
    GOOGLE_DRIVE_FOLDER_GRANTS {
      int id PK
      int user_id FK
      string folder_id
      string folder_id_hash
      string folder_name
      int can_add_children
      datetime validated_at
    }
    AUDIT_LOG {
      int id PK
      int actor_id FK
      string action
      string target_type
      text target_id
      text details
    }
```

Observações:

- o PDF não é armazenado em `CERTIFICATES`; ficam apenas localizador e metadados;
- `participant_document_hash` é HMAC versionado; o documento em claro é
  minimizado quando a configuração segura está ativa;
- `business_key` e `idempotency_key` resolvem problemas distintos: duplicidade
  acadêmica por linha e repetção da requisição de lote;
- `EMISSION_BATCH_ITEMS` usa chave composta única `(batch_id, row_number)`;
- o mapa evento→pasta fica cifrado em `EMISSION_BATCHES.context_ciphertext`;
- conexões OAuth guardam apenas material transitório cifrado, sem refresh token;
- somente uma versão de template pode estar ativa por vez.
