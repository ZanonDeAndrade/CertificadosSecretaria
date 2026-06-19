# Gerador de Certificados

Backend FastAPI para receber um arquivo Excel, combinar dados manuais do formulario, gerar certificados em PDF e expor os arquivos em `/certificates/...`.

## Requisitos

- Python 3.11+
- Dependencias em `requirements.txt`

## Instalacao

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Se estiver na raiz do projeto, entre primeiro em `backEnd/`.

## Execucao

```bash
python main.py
```

Ao executar, o backend sobe em `http://localhost:8000`.

## Endpoints

- `GET /health`
- `POST /generate-certificates`
- `GET /certificates/{arquivo}.pdf`

Os PDFs gerados ficam em `output/certificados/`.

## Contrato do Excel

Colunas esperadas:

- `nome`
- `email`
- `curso`

## Campos manuais enviados no multipart

- `texto_certificado` — texto padrao do corpo do certificado, aplicado a todos os participantes
- `data_emissao` — data de emissao exibida no rodape ("Restinga Seca, ...")

O nome de cada participante continua sendo lido do Excel e renderizado individualmente no certificado.
