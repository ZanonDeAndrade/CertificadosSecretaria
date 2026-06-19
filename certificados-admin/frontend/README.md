# Frontend de Certificados

Aplicacao React + Vite + TypeScript para enviar planilhas `.xlsx` ao backend
FastAPI, complementar dados manualmente e listar os certificados gerados.

## Instalar

```bash
npm install
```

## Executar em desenvolvimento

```bash
npm run dev
```

## Gerar build

```bash
npm run build
```

## Configuracao da API

Crie um arquivo `.env` com:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

## Fluxo de dados

O Excel deve conter:

- `nome`
- `email`
- `curso`

O formulario envia junto:

- `professor`
- `data_evento`
- `carga_horaria`
- `data_emissao`
