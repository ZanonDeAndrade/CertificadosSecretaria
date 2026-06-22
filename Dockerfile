# Imagem única usada pelos dois backends (admin e consulta) e pelo migrate.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Fontes para a geração de PDF no Linux (o repo já traz Times New Roman;
# Liberation/DejaVu cobrem Arial/Verdana etc. quando o template os usa) + tini.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-liberation fonts-dejavu-core curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala as dependências dos dois apps (a admin é superconjunto; a consulta
# acrescenta jinja2). Camada cacheável separada do código.
COPY certificados-admin/backEnd/requirements.txt /tmp/admin-reqs.txt
COPY certificados-consulta/requirements.txt /tmp/consulta-reqs.txt
RUN pip install --upgrade pip && \
    pip install -r /tmp/admin-reqs.txt -r /tmp/consulta-reqs.txt

COPY . /app

# Usuário não-root.
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000 8001
ENTRYPOINT ["/usr/bin/tini", "--"]
# O comando (uvicorn admin / uvicorn consulta / alembic) é definido no compose.
