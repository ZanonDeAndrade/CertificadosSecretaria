# Manual rápido da secretaria

Use somente dados autorizados. Para demonstração acadêmica, use exclusivamente
o modelo e participantes sintéticos.

## 1. Entrar

1. Abra o endereço administrativo institucional.
2. Informe usuário e senha. Nunca compartilhe a conta.
3. Se o sistema exigir troca de senha, conclua-a antes de continuar.
4. Confira o nome da instituição e seu perfil no menu.

## 2. Preparar o lote

1. Acesse **Emitir certificados**. Se o card indicar **Google Drive não
   conectado**, conecte a conta na tela oficial do Google antes de preparar o
   lote; assim o redirect não interrompe uma planilha já selecionada.
2. Baixe a planilha modelo.
3. Preencha ao menos `nome` e `carga_horaria`; revise curso, evento e datas.
   Na Mostra de Iniciação Científica sai um certificado por trabalho: use as
   colunas `autor1` a `autor8` (só `autor1` é obrigatória), `titulo_trabalho` e
   `equipe`; a carga horária é opcional. Baixe o modelo com o tipo já
   selecionado para receber as colunas certas.
4. Preencha `registro_academico` quando o participante precisar pesquisar ou
   liberar certificados pelo RA na consulta pública.
5. Salve como `.xlsx` e envie por seletor ou arrastar/soltar.

## 3. Validar e escolher os destinos

1. Revise o total de linhas válidas e inválidas.
2. Baixe o CSV de erros se necessário; corrija a planilha e valide novamente.
3. Leia o texto interpolado e confirme template, data e informações
   institucionais.
4. Avance para **Destino**. Se necessário, use **Conectar Google Drive** e conclua
   o login/consentimento na tela oficial do Google.
5. Para cada evento exibido, use **Selecionar pasta no Google Drive**. Linhas sem
   evento aparecem explicitamente como **Certificados sem evento** e também
   exigem uma pasta.
6. Confira somente o nome da pasta; o sistema não exibe seu identificador interno.
   É permitido trocar a pasta antes de confirmar. Depois de iniciado, o lote
   conserva os destinos inclusive em retry.
7. Pressione **Confirmar emissão** uma vez. A tela acompanha o lote persistente.
8. Se atualizar o navegador, retome pelo lote exibido; não crie outro lote para
   “destravar” sem antes consultar o status.

## 4. Conferir o resultado

O resumo separa gerados, duplicados, inválidos e falhos. Abra o histórico
filtrado pelo lote. Para falha persistente, anote apenas o identificador do lote
e o código de erro; não envie planilha ou Registro Acadêmico (RA) por canal informal.

## 5. Histórico e downloads

- filtre por nome, código, curso, evento, período, estado ou lote;
- abra o detalhe para verificar template, emissor, integridade e ciclo de vida;
- download individual ou ZIP só é oferecido quando autorizado e íntegro;
- itens revogados, ausentes ou bloqueados são ignorados/informados no ZIP.

## 6. Revogar e reemitir

Revogar exige motivo e confirmação. Não use o motivo para registrar dado
pessoal desnecessário. Reemita somente para correção autorizada; o sistema mantém
o código, os snapshots institucionais/template e a pasta original, e registra a
ação.

Desconectar o Google Drive impede novas escolhas/emissões, mas não apaga PDFs
nem altera certificados existentes.

## 7. Validação pública

O QR abre `/validar/<código>`. Um certificado ativo exibe metadados mínimos;
revogado exibe seu estado e não permite download. Busca por nome não revela o
código, nome ou RA; os dois últimos exigem confirmar o Registro Acadêmico (RA)
para liberar o arquivo.

## 8. Encerrar e comunicar incidente

Saia pelo menu ao terminar, especialmente em computador compartilhado. Em caso
de conta suspeita, certificado inesperado, integridade bloqueada ou exposição de
dado, encerre sessões e acione imediatamente o responsável institucional. Não
tente corrigir diretamente no banco ou no Drive.
