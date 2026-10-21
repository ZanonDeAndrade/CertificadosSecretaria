# Google Drive e OAuth

## Fluxo implementado

1. Um usuário com permissão de emissão inicia OAuth em `/integrations/google-drive/oauth/start`.
2. O backend gera `state` e PKCE, guarda somente valores cifrados no PostgreSQL
   e redireciona ao Google.
3. O callback confere `state`, troca o código, verifica o escopo `drive.file` e
   mantém o token de curta duração cifrado no banco.
4. O Picker seleciona uma pasta por evento; o backend valida tipo/permissões e
   registra o grant no banco.
5. O worker usa a credencial técnica configurada para gravar o PDF, registra
   `drive_file_id`, `drive_folder_id`, MIME, nome, tamanho e checksum e só então
   conclui o item. Falhas acionam retry/compensação da fila durável.

O token do Picker não é enviado ao frontend como credencial persistente. Segredos
de client/API key e credenciais técnicas devem usar arquivos ignorados ou secret
manager, nunca Git, Dockerfile ou bundle React.

## Desenvolvimento

O padrão é `STORAGE_PROVIDER=local`, portanto desenvolvimento e Docker local
funcionam sem internet ou Google. Para testar Drive de verdade, mude o provider
somente no arquivo local ignorado e forneça:

```text
GOOGLE_PICKER_CLIENT_ID
GOOGLE_PICKER_CLIENT_SECRET_FILE
GOOGLE_PICKER_API_KEY_FILE
GOOGLE_PICKER_APP_ID
GOOGLE_DRIVE_OAUTH_REDIRECT_URI
GOOGLE_DRIVE_UPLOAD_PRINCIPAL_EMAIL
GOOGLE_DRIVE_PUBLIC_READER_EMAIL
GOOGLE_DRIVE_AUTH_MODE
GOOGLE_ADMIN_OAUTH_TOKEN_FILE ou GOOGLE_ADMIN_SERVICE_ACCOUNT_FILE
GOOGLE_PUBLIC_OAUTH_TOKEN_FILE ou GOOGLE_PUBLIC_SERVICE_ACCOUNT_FILE
```

No Google Cloud Console, registre exatamente a origem JavaScript
`http://localhost:5173` (Vite) e o callback
`http://localhost:8000/integrations/google-drive/oauth/callback` quando usar o
modo nativo. Scheme, host, porta e caminho precisam coincidir exatamente.

## Servidor LAN sem domínio

O perfil LAN mantém `STORAGE_PROVIDER=local` de propósito. O restante do
sistema, inclusive emissão, fila, PDF, consulta e download, funciona sem
Google. Google OAuth web **não pode** usar `http://192.168.2.192/...` como
callback/origem: as regras do Google exigem HTTPS e proíbem IP bruto, com
exceção de localhost. Quando houver domínio controlado e HTTPS, registre o
callback HTTPS exato, configure as credenciais e migre para o perfil apropriado.

Essa limitação vem das regras oficiais de URI de redirecionamento do Google,
que aceitam HTTP/IP apenas para localhost e exigem correspondência exata do
callback. [Documentação Google OAuth](https://developers.google.com/identity/protocols/oauth2/web-server)

## Diagnóstico

- `redirect_uri_mismatch`: o callback não é idêntico ao registrado no Console.
- `401`/`403` do Drive: token revogado, escopo insuficiente, quota ou permissão
  da pasta; o lote fica visível para retry/falha, não é marcado como concluído.
- Picker indisponível: confira client ID, secret, API key e CSP do proxy.
- Drive indisponível: mantenha o perfil local para operação offline; não tente
  alternar provider no meio de um lote pendente.

Os testes automatizados cobrem OAuth/PKCE, state único, validação de pasta,
permissões, retry e persistência de IDs usando serviços simulados. A autorização
real no Google Console exige credenciais institucionais e permanece uma etapa
manual.
