# Contrato da planilha

Formato aceito: arquivo Office Open XML `.xlsx` real. Arquivos `.xls`, CSV ou um
ZIP renomeado não atendem ao contrato. O modelo oficial pode ser baixado na tela
de emissão.

## Colunas

| Coluna canônica | Obrigatória | Tipo/comportamento | Sinônimos aceitos (exemplos) |
|---|---:|---|---|
| `nome` | sim | texto não vazio | `name`, `participante`, `aluno`, `nome completo`. |
| `carga_horaria` | sim | primeiro inteiro positivo encontrado | `carga`, `ch`, `horas`, `workload`. |
| `curso` | não | curso conhecido é canonizado; desconhecido permanece como texto | `course`, `curso nome`. |
| `evento` | não | texto; é distinto de curso; disponível como `{{evento}}` no texto padrão | `event`, `atividade`, `nome evento`. |
| `data_emissao` | não | normalizada se reconhecida; pode vir da confirmação | `emissao`, `issue date`. |
| `data_inicio` | não | normalizada se reconhecida | `inicio`, `start`, `start date`. |
| `data_fim` | não | normalizada se reconhecida | `fim`, `termino`, `end date`. |
| `email` | não | texto; não é exposto publicamente | `e-mail`, `correio`. |
| `registro_academico` | não | Registro Acadêmico (RA) usado na consulta e confirmação pública | `ra`; por retrocompatibilidade: `documento`, `cpf`, `matricula`, `registro`. |
| `equipe` | não | texto; disponível como `{{equipe}}` no texto padrão e como elemento do template | `team`, `nome equipe`, `grupo`. |
| `titulo_trabalho` | não | texto; disponível como `{{titulo_trabalho}}` no texto padrão e como elemento do template | `titulo`, `trabalho`, `título do trabalho`, `title`. |
| `autor1` … `autor8` | só na Mostra (`autor1`) | autores do trabalho, em ordem; células vazias entre eles são ignoradas | `Autor 1`, `autor_1`, `Autor01`, `author1`, `coautor1`. |

## Certificado por trabalho (Mostra de Iniciação Científica)

No tipo *Mostra de Iniciação Científica* sai **um certificado por trabalho**,
válido para todos os autores dele:

- `autor1` é obrigatório; `nome` só é aceito como sinônimo de `autor1` quando a
  coluna `autor1` não existe;
- até oito autores; colunas `autor9` em diante são ignoradas e a Conferência
  avisa;
- `carga_horaria` é opcional; se o texto padrão usar `{{carga_horaria}}` e a
  célula vier vazia, a Conferência avisa a linha;
- o Autor 1 é o titular do registro (busca e RA); o nome do arquivo usa o
  título do trabalho, ou o Autor 1 quando o trabalho não tem título; os demais
  autores ficam gravados no certificado, aparecem na página pública de
  validação e também são encontrados pela busca por nome;
- o template do tipo pode ter o elemento **Autores**, que imprime
  `Autor N: Nome` só para os autores preenchidos, com a base fixa e crescendo
  para cima.

Cabeçalhos ignoram maiúsculas, acentos, espaços e pontuação. Se duas
colunas mapearem para o mesmo campo, a primeira reconhecida é usada. Colunas
extras são ignoradas.

## Variáveis do texto padrão

O texto padrão aceita `{{nome}}`, `{{carga_horaria}}`, `{{certificate_type}}`,
`{{evento}}`, `{{equipe}}` e `{{titulo_trabalho}}`, em qualquer tipo de
certificado. A tela de emissão recebe essa lista da API, então os botões de
inserir variável mostram exatamente o que o backend aceita. Qualquer outra
variável é recusada na validação. Se o texto usar uma variável que vem vazia
em alguma linha (por exemplo, `{{equipe}}` sem equipe), a Conferência avisa e
lista essas linhas, sem bloquear a emissão.

## Regras de arquivo e linha

- limite padrão: 2.000 linhas, configurável de 1 a 10.000;
- no máximo 50 colunas e 2.000 caracteres por célula;
- conteúdo descomprimido no máximo 80 MiB e razão de compressão até 200;
- tempo defensivo padrão de leitura: 20 segundos;
- linha totalmente vazia em `nome` e `carga_horaria` é ignorada;
- linha sem nome ou sem carga positiva é inválida e não gera certificado;
- campo opcional ausente não invalida a linha;
- data opcional não reconhecida é mantida como texto e deve ser revisada no
  preview;
- e-mail/Registro Acadêmico (RA) não aparecem no CSV de erros nem na auditoria;
- o RA não é persistido em texto puro: somente seu HMAC versionado é armazenado.

## Exemplo exclusivamente sintético

| nome | carga_horaria | curso | evento | data_emissao | registro_academico |
|---|---:|---|---|---|---|
| Pessoa Exemplo Alfa | 8 | Sistemas de Informação | Oficina Acadêmica Sintética | 10/06/2026 | MAT-DEMO-0001 |
| Pessoa Exemplo Beta | 12 horas | Direito | Jornada de Demonstração | 11/06/2026 | MAT-DEMO-0002 |

## Idempotência

A chave acadêmica por linha deriva de nome, Registro Acadêmico (RA), evento, curso, carga,
data de emissão e, quando resolvido, texto do certificado. O lote também recebe
uma `Idempotency-Key` associada ao hash da requisição completa. Reenviar o mesmo
conteúdo não deve criar duplicata; reutilizar a chave de lote para outro
conteúdo é conflito.
