# Limitações e trabalhos futuros

## Limitações reais

- Não houve deploy nem validação contra PostgreSQL gerenciado, Google Drive ou
  Secret Manager reais nesta entrega.
- E2E e screenshots usam build atual com API mock sintética. Backend e banco são
  testados separadamente; falta navegador contra a pilha completa real.
- OAuth, Google Picker, compartilhamento privado e as identidades técnicas de
  escrita/leitura foram exercitados somente com fakes. Antes da produção, um
  staging precisa comprovar seleção e upload em pastas reais, revogação do
  token pessoal e download pela identidade pública somente leitura.
- O hash SHA-256 detecta alteração dos bytes, mas não é assinatura digital
  ICP-Brasil nem prova jurídica de identidade do emissor.
- Não há MFA, SSO ou federação com identidade institucional.
- Não há envio de e-mail, integração com sistema acadêmico ou assinatura do
  aluno.
- A aplicação depende da disponibilidade e das cotas do PostgreSQL e Google
  Drive; nenhuma medição de SLA/carga de produção foi feita.
- Axe automatizado não substitui auditoria manual WCAG com tecnologia assistiva.
- O audit log não possui encadeamento criptográfico imutável contra acesso DBA.
- RPO, RTO, retenção jurídica, base legal e processo de titular dependem de
  decisão institucional.
- Há endpoint legado de geração mantido por compatibilidade; o fluxo canônico é
  o lote persistente.
- O ZIP acadêmico não inclui histórico Git nem documentos históricos, para
  evitar metadados/artefatos inadequados.

## Trabalhos futuros priorizados

1. staging isolado com PostgreSQL/Drive reais e dados sintéticos;
2. E2E HTTP completo, inclusive restart de worker e falha transitória do Drive;
3. MFA/SSO institucional e revisão de recuperação de conta;
4. assinatura digital institucional, se houver requisito jurídico;
5. teste manual de acessibilidade com leitor de tela e teclado;
6. carga/soak test com metas aprovadas e volume representativo sintético;
7. trilha de auditoria exportável/imutável com retenção definida;
8. automatizar reconciliação e restore drill em ambiente operacional isolado;
9. remover endpoint legado após inventário de consumidores;
10. formalizar custos, RPO/RTO, SLOs e runbooks de incidentes.

## Custos

Não há custo observado porque nenhum ambiente foi implantado. Os principais
direcionadores são compute das APIs/worker, instância e armazenamento/backup do
PostgreSQL, tráfego, armazenamento/cota do Drive, Secret Manager, logs e
monitoramento. Preços dependem de região, provedor, volume e contrato; portanto
este projeto não apresenta valor numérico sem uma cotação institucional datada.
