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

# Entrypoint script must be executable (the exec bit may be lost on Windows).
RUN chmod +x /app/deploy/entrypoint.sh

# Usuário não-root.
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000 8001
ENTRYPOINT ["/usr/bin/tini", "--"]
# Cloud Run / single-process platforms: use the image as-is (CMD picks the app
# via APP_TARGET and binds $PORT). Docker Compose overrides `command:` per
# service (admin :8000 / consulta :8001), so this default is ignored there.
CMD ["/app/deploy/entrypoint.sh"]
