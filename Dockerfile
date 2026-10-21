# syntax=docker/dockerfile:1.7

# Multi-arch index digests are intentionally pinned. Updating them is an
# explicit dependency-maintenance operation documented in docs/DEPENDENCIAS.md.
ARG PYTHON_IMAGE=python:3.12.13-alpine3.24@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df
ARG POSTGRES_IMAGE=postgres:16.14-alpine3.24@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777

FROM ${PYTHON_IMAGE} AS runtime-dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    SOURCE_DATE_EPOCH=1767225600
WORKDIR /source

RUN python -m venv /opt/certificados
COPY requirements/runtime.txt /tmp/runtime.txt
RUN /opt/certificados/bin/pip install --require-hashes -r /tmp/runtime.txt

# Build an installable wheel instead of copying the repository into runtime.
COPY pyproject.toml README.md ./
COPY certificados-admin/backEnd ./certificados-admin/backEnd
COPY certificados_consulta ./certificados_consulta
COPY database ./database
COPY observability ./observability
COPY storage_service ./storage_service
COPY scripts ./scripts
RUN python -m pip wheel --no-deps --wheel-dir /tmp/wheels . && \
    /opt/certificados/bin/pip install --no-deps /tmp/wheels/*.whl

FROM runtime-dependencies AS operations-dependencies
COPY requirements/ops.txt /tmp/ops.txt
RUN /opt/certificados/bin/pip install --require-hashes -r /tmp/ops.txt

FROM ${PYTHON_IMAGE} AS runtime

ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG SOURCE_URL=unknown
LABEL org.opencontainers.image.title="CertificadosSecretaria" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PATH=/opt/certificados/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/appuser \
    PORT=8000

RUN addgroup -S -g 10001 appuser && \
    adduser -S -D -u 10001 -G appuser -h /home/appuser -s /sbin/nologin appuser && \
    mkdir -p /app /tmp/certificados-downloads && \
    chown -R 10001:10001 /app /tmp/certificados-downloads

WORKDIR /app
COPY --from=runtime-dependencies /opt/certificados /opt/certificados
COPY alembic.ini ./alembic.ini
COPY database/migrations ./database/migrations
COPY --chmod=0555 deploy/entrypoint.sh ./deploy/entrypoint.sh

USER 10001:10001
EXPOSE 8000 8001
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD []

# Operational target adds pg_dump/pg_restore without an unpinned apt install.
# The PostgreSQL image and Python image share Alpine 3.24; /usr/local holds
# the pinned CPython runtime and /opt/certificados the hashed dependencies.
FROM ${POSTGRES_IMAGE} AS operations

ENV PATH=/opt/certificados/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/var/lib/postgresql \
    PORT=8000
WORKDIR /app
COPY --from=runtime-dependencies /usr/local /usr/local
COPY --from=operations-dependencies /opt/certificados /opt/certificados
COPY alembic.ini ./alembic.ini
COPY database/migrations ./database/migrations
COPY --chmod=0555 deploy/entrypoint.sh ./deploy/entrypoint.sh
# The image runs our entrypoint directly as the postgres user. gosu is unused,
# and the version bundled upstream was compiled with a vulnerable Go stdlib.
RUN rm /usr/local/bin/gosu
USER postgres
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD []
