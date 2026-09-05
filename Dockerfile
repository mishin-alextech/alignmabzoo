# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /build/frontend

COPY frontend/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        clustalo \
        hmmer \
    && rm -rf /var/lib/apt/lists/*

# Backend — устанавливаемый Python-пакет с ASGI-приложением app.main:app.
COPY backend/ /build/backend/
RUN pip install --no-cache-dir /build/backend

# ANARCI — локальная проверенная поставка. setup.py проекта скачивает
# germline-данные из сети, поэтому его намеренно не запускаем: копируем уже
# подготовленные пакет и HMM-базу непосредственно в образ.
COPY anarci-master/ /tmp/anarci/
RUN anarci_site="$(python -c 'import site; print(site.getsitepackages()[0])')" \
    && mkdir -p "$anarci_site/anarci" \
    && cp -a /tmp/anarci/lib/python/anarci/. "$anarci_site/anarci/" \
    && install -m 0755 /tmp/anarci/bin/ANARCI /usr/local/bin/ANARCI \
    && python -c "import anarci; from pathlib import Path; hmm = Path(anarci.__file__).parent / 'dat' / 'HMMs' / 'ALL.hmm'; assert hmm.is_file(), hmm" \
    && command -v ANARCI \
    && command -v hmmscan \
    && command -v clustalo \
    && ANARCI --help >/dev/null \
    && rm -rf /tmp/anarci

COPY backend/ /app/backend/
COPY --from=frontend-builder /build/frontend/dist/ /app/app/static/

# Единственное место для записываемых результатов job внутри контейнера.
RUN mkdir -p /app/jobs

WORKDIR /app/backend

EXPOSE 8000

CMD ["python", "-m", "gunicorn", "app.main:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--worker-class", "uvicorn.workers.UvicornWorker"]
