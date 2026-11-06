# Contrato da planilha

Formato aceito: arquivo Office Open XML `.xlsx` real. Arquivos `.xls`, CSV ou um
ZIP renomeado não atendem ao contrato. O modelo oficial pode ser baixado na tela
de emissão: a aba `certificados` traz só o cabeçalho, e a aba `Instruções`
explica cada coluna, com um exemplo. A aba `Instruções` nunca é lida; os dados
vêm da primeira aba que não se chama `Instruções`.

## Colunas

| Coluna canônica | Obrigatória | Tipo/comportamento | Sinônimos aceitos (exemplos) |
|---|---:|---|---|
| `nome` | sim | texto não vazio | `name`, `participante`, `aluno`, `nome completo`. |
| `email` | sim | e-mail válido (um `@` e domínio com ponto), normalizado em minúsculas e sem espaços; localiza e libera o certificado na consulta pública; nunca é exibido | `e-mail`, `correio`. |
| `carga_horaria` | não | primeiro inteiro positivo encontrado; obrigatória só se o texto padrão usar `{{carga_horaria}}` | `carga`, `ch`, `horas`, `workload`. |
| `curso` | não | curso conhecido é canonizado; desconhecido permanece como texto | `course`, `curso nome`. |
| `evento` | não (sim na Mostra) | texto; é distinto de curso; disponível como `{{evento}}` no texto padrão | `event`, `atividade`, `nome evento`. |
| `data_emissao` | não | normalizada se reconhecida; pode vir da confirmação | `emissao`, `issue date`. |
| `data_inicio` | não | normalizada se reconhecida | `inicio`, `start`, `start date`. |
| `data_fim` | não | normalizada se reconhecida | `fim`, `termino`, `end date`. |
| `registro_academico` | não | Registro Acadêmico (RA); na consulta pública só confirma o download de certificados emitidos antes do cadastro de e-mail | `ra`; por retrocompatibilidade: `documento`, `cpf`, `matricula`, `registro`. |
| `equipe` | não | texto; disponível como `{{equipe}}` no texto padrão e como elemento do template | `team`, `nome equipe`, `grupo`. |
| `titulo_trabalho` | não (sim na Mostra) | texto; disponível como `{{titulo_trabalho}}` no texto padrão e como elemento do template | `titulo`, `trabalho`, `título do trabalho`, `title`. |
| `autor1` … `autor8` | só na Mostra (`autor1`) | autores do trabalho, em ordem; células vazias entre eles são ignoradas | `Autor 1`, `autor_1`, `Autor01`, `author1`, `coautor1`. |
| `email1` … `email8` | só na Mostra (`email1`, e o do mesmo número de cada autor preenchido) | e-mail de cada autor, validado e normalizado como `email`; `email` vale como `email1` quando a coluna não existe | `E-mail 1`, `email_1`, `Email do autor 1`, `emailautor1`. |

## Certificado por trabalho (Mostra de Iniciação Científica)

No tipo *Mostra de Iniciação Científica* sai **um certificado por trabalho**,
válido para todos os autores dele:

- `autor1`, `email1`, `evento` e `titulo_trabalho` são obrigatórios; a linha
  sem algum deles é inválida. `nome` só é aceito como sinônimo de `autor1`, e
  `email` de `email1`, quando a coluna numerada não existe;
- cada autor preenchido precisa do e-mail de mesmo número (`autor3` ↔
  `email3`); autor sem e-mail, e-mail sem autor ou e-mail inválido invalidam a
  linha;
- até oito autores; colunas `autor9` em diante são ignoradas e a Conferência
  avisa;
- `carga_horaria` é opcional; se o texto padrão usar `{{carga_horaria}}` e a
  célula vier vazia, a linha é inválida (o texto sairia sem o número);
- o Autor 1 é o titular do registro; o arquivo gravado usa o título do
  trabalho (`Título do trabalho_Evento_Ano.pdf`), ou o Autor 1 quando o
  trabalho não tem título; o download entrega uma cópia do mesmo PDF por autor
  (`Nome do autor_Evento_Ano.pdf`), em ZIP ou uma a uma; os demais autores
  ficam gravados no certificado, aparecem na página pública de validação e
  também são encontrados pela busca por nome e, pelo e-mail de cada um, pela
  busca por e-mail;
- nenhum nome fica em destaque. O tipo exige um template ativo **próprio**,
  nunca o genérico, sem o elemento **Nome do participante**, com o **Corpo** e
  com o bloco **Autores**. Sem isso, a Conferência bloqueia a confirmação e a
  API recusa o lote com 422. O bloco imprime `Autores:` e um nome por linha
  (`Autor:` quando há um só), sem numeração, com a base fixa e crescendo para
  cima, acima do QR Code. No editor, escolher o tipo monta esse ponto de
  partida a partir da versão copiada;
- com o texto padrão em branco vale o texto automático: `Certificamos que o
  trabalho "{titulo}" foi apresentado no evento {evento}.`, com `, com carga
  horária de N horas` antes do ponto quando a carga vem preenchida. Um texto
  próprio substitui o automático, mas não pode usar `{{nome}}`, que imprimiria
  só o primeiro autor.

Cabeçalhos ignoram maiúsculas, acentos, espaços e pontuação. Se duas
colunas mapearem para o mesmo campo, a primeira reconhecida é usada. Colunas
extras são ignoradas.

## Variáveis do texto padrão

O texto padrão aceita `{{nome}}`, `{{carga_horaria}}`, `{{certificate_type}}`,
`{{evento}}`, `{{equipe}}` e `{{titulo_trabalho}}`, em qualquer tipo de
certificado, exceto `{{nome}}` na Mostra. A tela de emissão recebe essa lista da API, então os botões de
inserir variável mostram exatamente o que o backend aceita. Qualquer outra
variável é recusada na validação. Se o texto usar uma variável que vem vazia
em alguma linha (por exemplo, `{{equipe}}` sem equipe), a Conferência avisa e
lista essas linhas, sem bloquear a emissão. A exceção é `{{carga_horaria}}`:
com a carga vazia, a linha é inválida na Conferência e a API recusa o lote,
porque o certificado sairia com "carga horária de  horas".

## Regras de arquivo e linha

- limite padrão: 2.000 linhas, configurável de 1 a 10.000;
- no máximo 50 colunas e 2.000 caracteres por célula;
- conteúdo descomprimido no máximo 80 MiB e razão de compressão até 200;
- tempo defensivo padrão de leitura: 20 segundos;
- linha totalmente vazia em `nome`, `email` e `carga_horaria` é ignorada;
- linha sem nome, sem e-mail ou com e-mail inválido é inválida e não gera
  certificado; carga preenchida com algo que não é um inteiro positivo também;
- campo opcional ausente não invalida a linha;
- célula que ainda tem um texto de exemplo de modelos antigos (`Nome completo`,
  `Nome do primeiro autor`, `Segundo autor (opcional)`, `Nome da mostra`,
  `Curso (opcional)`, `Evento (opcional)`, `Equipe (opcional)`,
  `Título do trabalho (opcional)`, sem diferenciar maiúsculas e espaços)
  invalida a linha, porque o texto sairia no certificado;
- data opcional não reconhecida é mantida como texto e deve ser revisada no
  preview;
- e-mail/Registro Acadêmico (RA) não aparecem no CSV de erros, na auditoria, nos
  logs nem em nenhuma resposta do site público;
- o RA não é persistido em texto puro: somente seu HMAC versionado é armazenado.
  Para a busca pública, o mesmo vale para todos os e-mails da linha
  (`certificate_email_hashes`, um por autor, com a versão da chave); o e-mail
  do titular fica também em texto no registro, visível só no detalhe do painel
  e apagado pela retenção de dados.

## Exemplo exclusivamente sintético

| nome | email | carga_horaria | curso | evento | data_emissao | registro_academico |
|---|---|---:|---|---|---|---|
| Pessoa Exemplo Alfa | alfa@exemplo.com | 8 | Sistemas de Informação | Oficina Acadêmica Sintética | 10/06/2026 | MAT-DEMO-0001 |
| Pessoa Exemplo Beta | beta@exemplo.com | | Direito | Jornada de Demonstração | 11/06/2026 | |

## Idempotência

A chave acadêmica por linha deriva de nome, Registro Acadêmico (RA), evento, curso, carga,
data de emissão e, quando resolvido, texto do certificado; o e-mail não entra
nela, então uma planilha antiga reenviada com a coluna acrescentada continua
não duplicando certificados. O lote também recebe
uma `Idempotency-Key` associada ao hash da requisição completa. Reenviar o mesmo
conteúdo não deve criar duplicata; reutilizar a chave de lote para outro
conteúdo é conflito.
