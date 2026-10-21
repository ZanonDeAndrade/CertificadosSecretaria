# Plano de backup e recuperação

## Escopo e objetivos

O backup cobre PostgreSQL e, opcionalmente, PDFs do Drive. Artefatos usam
streaming e AES-256-GCM. O projeto não define RPO/RTO numéricos: eles dependem
do calendário acadêmico, volume e infraestrutura e devem ser aprovados pela
instituição. Sem essa decisão, produção permanece pendente.

## Pré-requisitos

- imagem operacional com `pg_dump`/`pg_restore` compatíveis;
- `DATABASE_URL` somente leitura suficiente para dump;
- `BACKUP_ENCRYPTION_KEY` de 32 bytes em base64, exclusiva e fora do banco;
- destino `gs://bucket/prefixo-dedicado` separado do workload em produção;
- `RESTORE_DATABASE_URL` para banco descartável cujo nome contenha `restore` ou
  `drill`;
- credencial separada para o bucket e, se PDFs forem incluídos, acesso controlado
  ao Drive.

## Criar e verificar

```bash
uv run certificados-backup create --destination gs://BUCKET/certificados --retention-days 35
uv run certificados-backup verify --artifact CAMINHO_DO_ARTEFATO.csbk
```

O relatório do comando deve registrar tipo, tamanho em claro, SHA-256, contagem e
horário sem nomes de participantes, URLs com senha ou chave. Em produção,
destino local é recusado.

## Restore drill

```bash
uv run certificados-backup restore-drill \
  --database-artifact CAMINHO_DB.csbk \
  --pdf-artifact CAMINHO_PDFS.csbk \
  --restore-files \
  --report /tmp/restore-drill.json
```

O comando deve:

1. recusar o banco de produção e alvo sem nome descartável;
2. autenticar o artefato antes de confiar nos dados;
3. restaurar com `--clean --if-exists --exit-on-error`;
4. aplicar/verificar migration e invariantes;
5. validar manifesto/PDFs e limpar arquivos temporários;
6. produzir relatório redigido;
7. permitir apagar banco e arquivos do drill ao final.

Backup nunca restaurado é considerado não testado. Um drill deve ocorrer antes
da primeira produção, depois de mudança relevante no schema/backup e em agenda
institucional.

## Recuperação de incidente

1. interromper escritas e preservar evidência;
2. determinar ponto de recuperação autorizado;
3. restaurar primeiro em ambiente isolado;
4. validar migrations, contagens, constraints, templates, jobs e hashes;
5. reconciliar PostgreSQL × Drive sem publicar arquivos;
6. executar smoke sintético e teste negativo de acesso;
7. obter aprovação para troca de tráfego;
8. documentar perda de dados, RPO/RTO observado e ações corretivas.

## Rotação e retenção

Ao rotacionar a chave, mantenha a versão anterior enquanto existirem backups
que dependem dela. A chave não deve ficar no mesmo bucket. A exclusão por
retenção deve respeitar legal hold e ser testada sem apagar o último ponto
restaurável aprovado.
