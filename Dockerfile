# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /build/frontend

COPY frontend/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim-bookworm AS mmseqs-builder

ARG MMSEQS_REPOSITORY=https://github.com/soedinglab/MMseqs2.git
ARG MMSEQS_GIT_REF=master

WORKDIR /build

ENV PATH=/root/.cargo/bin:$PATH

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        cmake \
        curl \
        g++ \
        git \
        make \
        zlib1g-dev \
        libbz2-dev \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --profile minimal --default-toolchain stable \
    && rustc --version \
    && cargo --version \
    && mkdir mmseqs2 \
    && cd mmseqs2 \
    && git init \
    && git remote add origin "$MMSEQS_REPOSITORY" \
    && git fetch --depth 1 origin "$MMSEQS_GIT_REF" \
    && git checkout --detach FETCH_HEAD \
    && git rev-parse HEAD > /build/mmseqs2-revision \
    && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/mmseqs2 \
    && cmake --build build --parallel 2 \
    && cmake --install build \
    && rm -rf /var/lib/apt/lists/* /build/mmseqs2/.git


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/opt/mmseqs2/bin:$PATH

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        clustalo \
        hmmer \
        libgomp1 \
        libbz2-1.0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=mmseqs-builder /opt/mmseqs2/ /opt/mmseqs2/
COPY --from=mmseqs-builder /build/mmseqs2-revision /usr/local/share/mmseqs2-revision

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
    && command -v mmseqs \
    && ANARCI --help >/dev/null \
    && mmseqs version \
    && rm -rf /tmp/anarci

COPY backend/ /app/backend/
COPY --from=frontend-builder /build/frontend/dist/ /app/app/static/

# Единственное место для записываемых результатов job внутри контейнера.
RUN mkdir -p /app/jobs

WORKDIR /app/backend

EXPOSE 8000

CMD ["python", "-m", "gunicorn", "app.main:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker"]
